from __future__ import annotations

import logging

from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from pydantic import BaseModel

from .agent import build_app
from .config import RECURSION_LIMIT, ROOT
from .guardrails import check_input
from .schemas import AnswerSchema
from .tracing import TraceCollector, extract_final_answer

logger = logging.getLogger("agent_router")

app = FastAPI(title="AI 워크플로우 라우팅 에이전트 API", version="0.1.0")

_STATIC_DIR = ROOT / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# 에러 처리 - 기본값은 모든 예외를 뭉뚱그려 "Internal Server Error"로만 응답하므로,
# 실제로 자주 겪는 Bedrock 오류(일일 토큰 한도·모델 접근 권한)는 원인을 바로 알 수 있게
# 구분해서 응답하고, 그 외 예외도 최소한 타입·메시지는 그대로 내려준다. 전체 스택트레이스는
# 서버 로그에만 남기고 응답에는 포함하지 않는다(파일 경로 등 내부 정보 노출 방지).
# ---------------------------------------------------------------------------


def _find_client_error(exc: BaseException) -> ClientError | None:
    """예외 체인(원인/컨텍스트)을 따라가며 botocore ClientError를 찾는다.
    LangGraph는 노드 실행 실패 시 원본 예외를 그대로 재발생시키므로 보통 exc 자체가
    ClientError지만, 다른 레이어가 감싸는 경우에 대비해 체인도 확인한다."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ClientError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _bedrock_error_response(exc: ClientError) -> JSONResponse:
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    message = error.get("Message", str(exc))

    if code == "ThrottlingException":
        return JSONResponse(
            status_code=429,
            content={
                "error": "BEDROCK_THROTTLED",
                "message": "AWS Bedrock 일일 토큰 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
                "detail": message,
            },
        )
    if code == "AccessDeniedException":
        return JSONResponse(
            status_code=502,
            content={
                "error": "BEDROCK_ACCESS_DENIED",
                "message": "이 IAM 계정에는 설정된 Bedrock 모델을 호출할 권한이 없습니다. src/config.py의 COMPASS_MODEL_* 값을 확인하세요.",
                "detail": message,
            },
        )
    return JSONResponse(
        status_code=502,
        content={"error": code or "BEDROCK_ERROR", "message": message},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)

    if isinstance(exc, GraphRecursionError):
        return JSONResponse(
            status_code=500,
            content={
                "error": "GRAPH_RECURSION_LIMIT",
                "message": (
                    f"에이전트 실행이 안전 상한({RECURSION_LIMIT}스텝)을 넘어 중단되었습니다 - "
                    "서브에이전트 간 라우팅이 반복되거나 도구 호출이 계속 이어졌을 수 있습니다."
                ),
            },
        )

    client_error = _find_client_error(exc)
    if client_error is not None:
        return _bedrock_error_response(client_error)

    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc) or "알 수 없는 서버 오류가 발생했습니다.",
        },
    )


@app.get("/")
async def ui() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


_REJECT_KEYWORDS = ["취소", "아니", "거절", "그만", "no", "cancel", "reject"]


class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None


def _parse_resume_decision(text: str) -> dict:
    lowered = text.lower()
    if any(k in text or k in lowered for k in _REJECT_KEYWORDS):
        return {"decisions": [{"type": "reject", "message": text}]}
    return {"decisions": [{"type": "approve"}]}


def _format_interrupt_answer(interrupt_value: dict) -> str:
    action = interrupt_value["action_requests"][0]
    return (
        "다음 작업은 실행 전 승인이 필요합니다.\n"
        f"- 도구: {action['name']}\n"
        f"- 내용: {action['args']}\n"
        "승인하시려면 '승인', 취소하시려면 '취소'라고 답해 주세요."
    )


@app.post("/query", response_model=AnswerSchema)
async def query(req: QueryRequest) -> AnswerSchema:
    thread_id = req.session_id or "default"
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_app()

    state = await graph.aget_state(config)
    is_resuming = bool(state.tasks) and any(getattr(t, "interrupts", None) for t in state.tasks)

    if not is_resuming:
        guard_message = check_input(req.question)
        if guard_message is not None:
            return AnswerSchema(answer=guard_message, contexts=[], trace=[])

    tracer = TraceCollector()
    run_config = {**config, "callbacks": [tracer], "recursion_limit": RECURSION_LIMIT}

    if is_resuming:
        payload = Command(resume=_parse_resume_decision(req.question))
    else:
        payload = {"messages": [HumanMessage(content=req.question)]}

    result = await graph.ainvoke(payload, config=run_config)

    if "__interrupt__" in result:
        approval_notice = _format_interrupt_answer(result["__interrupt__"][0].value)
        # interrupt 직전까지 서브에이전트가 만든 답변(예: research_agent의 복잡도 판정·근거)이 있으면
        # 승인 요청 문구만 보여주고 버리지 않는다 - 사용자가 "왜 이 비용/파이프라인이냐"를 승인 시점에
        # 다시 볼 수 있어야 한다.
        prior_answer = extract_final_answer(result["messages"])
        answer_text = (
            f"{prior_answer}\n\n---\n\n{approval_notice}"
            if prior_answer and prior_answer != "(응답을 생성하지 못했습니다)"
            else approval_notice
        )
        return AnswerSchema(
            answer=answer_text,
            contexts=tracer.extract_contexts(),
            trace=tracer.steps,
            assignment_summary=result["__interrupt__"][0].value,
        )

    answer_text = extract_final_answer(result["messages"])

    tracer.write_log(req.question, answer_text, thread_id)

    return AnswerSchema(
        answer=answer_text,
        contexts=tracer.extract_contexts(),
        trace=tracer.steps,
        assignment_summary=tracer.extract_assignment_summary(),
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

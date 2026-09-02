from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from .agent import build_app
from .config import ROOT
from .guardrails import check_input
from .schemas import AnswerSchema
from .tracing import TraceCollector, extract_final_answer

app = FastAPI(title="나침반(Compass) API", version="0.1.0")

_STATIC_DIR = ROOT / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


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
    run_config = {**config, "callbacks": [tracer]}

    if is_resuming:
        payload = Command(resume=_parse_resume_decision(req.question))
    else:
        payload = {"messages": [HumanMessage(content=req.question)]}

    result = await graph.ainvoke(payload, config=run_config)

    if "__interrupt__" in result:
        answer_text = _format_interrupt_answer(result["__interrupt__"][0].value)
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

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from .config import TRACE_LOG_PATH
from .schemas import Context, TraceStep

_HANDOFF_FILLER_TEXTS = {"Transferring back to supervisor"}


def _safe(value: Any) -> Any:
    # LangGraph의 ToolNode는 도구 반환값(list/dict)을 콜백에 넘기기 전에 이미 JSON 문자열로
    # 직렬화해 둔다 - contexts 추출 등에서 다시 쓸 수 있도록 여기서 원래 구조로 되돌린다.
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if hasattr(value, "content"):
            return _safe(value.content)
        return str(value)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(t for t in texts if t.strip()).strip()
    return ""


def extract_final_answer(messages: list) -> str:
    """create_supervisor 는 서브에이전트가 실제 답을 낸 뒤에도 두 가지를 더 붙인다:
    (1) "Transferring back to supervisor" 같은 handoff 필러 메시지, (2) 제어를 돌려받은 supervisor
    자신의 후속 메시지(우리 프롬프트상 supervisor는 절대 직접 답하지 않기로 되어 있으니 내용이 있어도
    보통 라우팅 후일담이라 사용자에게 보여줄 답이 아니다). 그래서 마지막 메시지가 아니라
    "서브에이전트(name != supervisor)가 낸 실제 텍스트가 있는 마지막 AIMessage"를 우선 찾는다."""
    fallback = ""
    for m in reversed(messages):
        if m.__class__.__name__ != "AIMessage":
            continue
        text = _text_of(m.content)
        if not text or text in _HANDOFF_FILLER_TEXTS:
            continue
        name = getattr(m, "name", None)
        if name and name != "supervisor":
            return text
        if not fallback:
            fallback = text
    return fallback or "(응답을 생성하지 못했습니다)"


class TraceCollector(BaseCallbackHandler):
    """Day7 Observability 패턴 - 기존 코드 수정 없이 콜백으로 도구 호출 전체를 추적한다."""

    def __init__(self) -> None:
        self.steps: list[TraceStep] = []
        self._pending: dict[UUID, dict] = {}

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):  # noqa: D102
        name = (serialized or {}).get("name") or "tool"
        self._pending[run_id] = {"name": name, "input": _safe(inputs if inputs is not None else input_str)}

    def on_tool_end(self, output, *, run_id, **kwargs):  # noqa: D102
        info = self._pending.pop(run_id, {"name": "tool", "input": None})
        self.steps.append(TraceStep(step=info["name"], input=info["input"], output=_safe(output)))

    def on_tool_error(self, error, *, run_id, **kwargs):  # noqa: D102
        info = self._pending.pop(run_id, {"name": "tool", "input": None})
        self.steps.append(TraceStep(step=info["name"], input=info["input"], output={"error": str(error)}))

    def extract_contexts(self) -> list[Context]:
        contexts: list[Context] = []
        seen: set[tuple[str, str]] = set()
        for step in self.steps:
            if step.step != "retrieve_docs" or not isinstance(step.output, list):
                continue
            for chunk in step.output:
                if not isinstance(chunk, dict) or "doc_id" not in chunk:
                    continue
                key = (chunk["doc_id"], chunk.get("text", "")[:50])
                if key in seen:
                    continue
                seen.add(key)
                contexts.append(Context(doc_id=chunk["doc_id"], text=chunk.get("text", ""), score=chunk.get("score")))
        return contexts

    def extract_assignment_summary(self) -> dict | None:
        for step in reversed(self.steps):
            if step.step in ("commit_pipeline", "track_assignment", "revise_assignment") and isinstance(
                step.output, dict
            ):
                return step.output
        return None

    def write_log(self, question: str, answer: str, thread_id: str) -> None:
        record = {
            "thread_id": thread_id,
            "question": question,
            "answer": answer,
            "trace": [s.model_dump() for s in self.steps],
        }
        with open(TRACE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

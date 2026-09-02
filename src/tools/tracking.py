from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from .. import data_store
from ._mcp import ensure_mcp_tools, parse_mcp_result

# ---------------------------------------------------------------------------
# track_assignment
# ---------------------------------------------------------------------------


@tool
def track_assignment(assignment_id: str) -> dict:
    """assignment_id로 진행 단계와 실측 vs 예상 비용을 조회한다."""
    a = data_store.get_assignment(assignment_id)
    if a is None:
        return {"status": "NOT_FOUND", "message": f"assignment {assignment_id} 를 찾을 수 없습니다."}
    return a


# ---------------------------------------------------------------------------
# revise_assignment (MCP + HITL 승인 게이트, 상태변경)
# ---------------------------------------------------------------------------


@tool
async def revise_assignment(assignment_id: str, action: Literal["cancel", "renegotiate"], reason: str) -> dict:
    """[승인 필요] RECOMMENDED/APPROVED 단계는 취소(cancel)하고, IN_PROGRESS 이후는 취소 대신 스코프 축소/재협상(renegotiate) 사유만 기록한다."""
    tools = await ensure_mcp_tools()
    if action == "cancel":
        raw = await tools["execute_cancel"].ainvoke({"assignment_id": assignment_id})
    else:
        raw = await tools["execute_revise"].ainvoke({"assignment_id": assignment_id, "reason": reason})
    return parse_mcp_result(raw)

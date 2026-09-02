from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from .. import data_store
from ._mcp import ensure_mcp_tools, parse_mcp_result

# ---------------------------------------------------------------------------
# get_token_budget (MCP, 읽기전용 - 승인 불필요)
# ---------------------------------------------------------------------------


@tool
async def get_token_budget() -> dict:
    """팀의 토큰 예산(잔액·월예산 잔여·1건 한도)을 조회한다. budget-mcp 서버를 통해 조회한다."""
    tools = await ensure_mcp_tools()
    result = await tools["get_token_budget"].ainvoke({})
    return parse_mcp_result(result)


# ---------------------------------------------------------------------------
# commit_pipeline (MCP + HITL 승인 게이트, 상태변경)
# ---------------------------------------------------------------------------


@tool
async def commit_pipeline(task_id: str, committed_cost: float, pipeline: str, config: RunnableConfig) -> dict:
    """[승인 필요] 파이프라인을 확정하고 팀 예산을 원자적으로 차감한다. 실행 직전 가격·슬롯 가용성을 재검증한다."""
    thread_id = config.get("configurable", {}).get("thread_id", "default")
    is_recheck = data_store.touch_task(thread_id, task_id)
    event = data_store.get_price_event(task_id) if is_recheck else None

    if event is not None:
        effect = event["effect"]
        if effect.get("block_commit"):
            return {
                "status": "BLOCKED",
                "reason_code": event["reason"],
                "message": event["message"],
                "balance_unchanged": True,
                "suggested_alternatives": event.get("suggested_alternatives", []),
            }
        if "set_estimated_cost" in effect:
            return {
                "status": "PRICE_CHANGED",
                "old_cost": committed_cost,
                "new_cost": effect["set_estimated_cost"],
                "message": event["message"],
                "requires_reapproval": True,
            }

    tools = await ensure_mcp_tools()
    raw = await tools["execute_commit"].ainvoke(
        {"task_id": task_id, "committed_cost": committed_cost, "pipeline": pipeline}
    )
    return parse_mcp_result(raw)

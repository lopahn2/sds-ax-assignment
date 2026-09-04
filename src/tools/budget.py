from __future__ import annotations

from langchain_core.tools import tool

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
async def commit_pipeline(task_id: str, committed_cost: float, pipeline: str) -> dict:
    """[승인 필요] 파이프라인을 확정하고 팀 예산을 원자적으로 차감한다. 잔액 부족·1건 한도 초과면
    아무것도 반영하지 않고 REJECTED를 반환한다."""
    tools = await ensure_mcp_tools()
    raw = await tools["execute_commit"].ainvoke(
        {"task_id": task_id, "committed_cost": committed_cost, "pipeline": pipeline}
    )
    return parse_mcp_result(raw)

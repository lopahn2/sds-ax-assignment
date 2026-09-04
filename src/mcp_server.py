"""budget-mcp - 팀 토큰 예산·assignment 원장을 감싸는 MCP(stdio) 서버.

사내 예산 시스템을 별도 프로세스로 노출한다는 가정을 재현한다 (SERVICE.md 패턴 5).
승인 게이트(HITL)는 이 서버가 아니라 이 서버를 호출하는 LangGraph 쪽 로컬 도구(src/tools/budget.py)에서 건다 -
MCP 서버 프로세스는 LangGraph의 checkpointer/interrupt 컨텍스트를 알지 못하기 때문이다.

실행: python src/mcp_server.py  (stdio)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from src import data_store  # noqa: E402

mcp = FastMCP("budget-mcp")


@mcp.tool()
def get_token_budget() -> dict:
    """팀의 토큰 예산(잔액·월예산·잔여·1건 한도)을 조회한다."""
    budget = data_store.get_budget()
    remaining = round(budget["monthly_budget"] - budget["monthly_spent"], 2)
    return {
        "team_id": budget["team_id"],
        "balance": budget["balance"],
        "monthly_budget": budget["monthly_budget"],
        "monthly_spent": budget["monthly_spent"],
        "monthly_remaining": remaining,
        "single_task_limit": budget["limits"]["single_task_limit"],
        "masked_billing_account": budget["billing_account"]["masked_account_id"],
    }


@mcp.tool()
def execute_commit(task_id: str, committed_cost: float, pipeline: str) -> dict:
    """[승인 완료 후에만 호출] 예산을 원자적으로 차감하고 assignment를 생성한다."""
    try:
        result = data_store.commit_assignment(task_id, committed_cost, pipeline)
        return {"status": "COMMITTED", "assignment": result}
    except data_store.LedgerError as e:
        return {"status": "REJECTED", "reason_code": e.code, "message": e.message}


if __name__ == "__main__":
    mcp.run()

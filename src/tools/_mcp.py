from __future__ import annotations

import json

from langchain_mcp_adapters.client import MultiServerMCPClient

from ..config import MCP_PYTHON, MCP_SERVER_SCRIPT

# ---------------------------------------------------------------------------
# MCP(budget-mcp) 클라이언트 - 예산 조회·커밋을 별도 stdio 프로세스로 감싼다 (패턴 5)
# ---------------------------------------------------------------------------

_mcp_client: MultiServerMCPClient | None = None
_mcp_raw_tools: dict | None = None


async def ensure_mcp_tools() -> dict:
    global _mcp_client, _mcp_raw_tools
    if _mcp_raw_tools is None:
        _mcp_client = MultiServerMCPClient(
            {
                "budget": {
                    "command": MCP_PYTHON,
                    "args": [MCP_SERVER_SCRIPT],
                    "transport": "stdio",
                }
            }
        )
        tools_list = await _mcp_client.get_tools()
        _mcp_raw_tools = {t.name: t for t in tools_list}
    return _mcp_raw_tools


def parse_mcp_result(result) -> dict:
    if isinstance(result, list) and result and isinstance(result[0], dict) and "text" in result[0]:
        return json.loads(result[0]["text"])
    if isinstance(result, str):
        return json.loads(result)
    return result

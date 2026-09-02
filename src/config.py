from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"

# AWS Bedrock 자격증명(AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)은 boto3 기본 체인이 .env에서 읽은
# 환경변수를 그대로 사용한다 - 여기서 별도로 읽어 전달할 필요는 없다.
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", os.getenv("AWS_REGION", "us-east-1"))

# 서브그래프별 모델. 원래 설계는 판정 라우터에만 저비용(Haiku)을 쓰는 것이었으나(나침반이 다루는
# "복잡도에 안 맞는 비싼 모델을 쓰지 마라" 원칙을 나침반 자신에게도 적용), 이 계정의 IAM 사용자는
# 한동안 Sonnet 계열만 호출 가능했고 일일 토큰 한도(ThrottlingException)에 자주 걸렸다. 2026-09-02
# 중 Haiku 접근 권한이 추가로 열려서, 이제 원래 설계 의도대로 되돌린다: 자주(중첩으로) 호출되는
# classify_complexity(판정 라우터)와 상대적으로 가벼운 tracking_agent를 Haiku로 옮기고, Supervisor/
# research_agent/budget_agent 3개 실시간 핵심 역할만 서로 다른 Sonnet 버킷을 하나씩 전담한다 - 한
# 모델 ID에 여러 역할이 몰리지 않게 해서 Bedrock의 모델별 일일 토큰 한도 소진을 늦춘다(한도가 계정
# 전체가 아니라 모델 ID 단위로 걸리는 것으로 실측됨). 역할 구분 자체는 여전히 "추론 강도"(extended
# thinking budget, src/llm.py 참고)로도 함께 흉내낸다: Opus->extra, Sonnet->high, Haiku->low.
_MODEL_A = "global.anthropic.claude-sonnet-4-6"
_MODEL_B = "us.anthropic.claude-sonnet-4-6"
_MODEL_C = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
_HAIKU_A = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_HAIKU_B = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

MODEL_SUPERVISOR = os.getenv("COMPASS_MODEL_SUPERVISOR", _MODEL_C)
MODEL_RESEARCH = os.getenv("COMPASS_MODEL_RESEARCH", _MODEL_B)
MODEL_BUDGET = os.getenv("COMPASS_MODEL_BUDGET", _MODEL_A)
MODEL_TRACKING = os.getenv("COMPASS_MODEL_TRACKING", _HAIKU_A)
MODEL_ROUTER = os.getenv(
    "COMPASS_MODEL_ROUTER", _HAIKU_B
)  # classify_complexity 전용 - 판정만 하면 되므로 원래 의도대로 Haiku
# 오프라인 평가(run_eval.py judge)는 실시간 경로와 무관하고 채점 품질이 중요하므로 Sonnet 유지.
MODEL_JUDGE = os.getenv("COMPASS_MODEL_JUDGE", _MODEL_A)

# 역할별 추론 강도(reasoning tier) - Opus->extra, Sonnet->high, Haiku->low 매핑을 그대로 사용.
# classify_complexity는 get_structured_llm(강제 tool-calling, thinking 항상 off)을 쓰므로 별도
# 추론 강도 설정이 필요 없다 - REASONING_ROUTER 같은 값은 두지 않는다(죽은 설정이 되므로).
REASONING_SUPERVISOR = os.getenv("COMPASS_REASONING_SUPERVISOR", "high")
REASONING_RESEARCH = os.getenv("COMPASS_REASONING_RESEARCH", "high")
REASONING_BUDGET = os.getenv("COMPASS_REASONING_BUDGET", "high")
REASONING_TRACKING = os.getenv("COMPASS_REASONING_TRACKING", "low")
REASONING_JUDGE = os.getenv("COMPASS_REASONING_JUDGE", "extra")

MCP_SERVER_SCRIPT = str(ROOT / "src" / "mcp_server.py")
MCP_PYTHON = os.getenv("COMPASS_MCP_PYTHON") or __import__("sys").executable

TEAM_ID = os.getenv("COMPASS_TEAM_ID", "team_ai-enablement")
BUDGET_PERIOD = "2026-09"

TRACE_LOG_PATH = ROOT / "trace.jsonl"

RAG_TOP_K = int(os.getenv("COMPASS_RAG_TOP_K", "4"))

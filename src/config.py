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

# 서브그래프별 모델. 원래 설계는 판정 라우터에만 저비용(Haiku)을 쓰는 것이었으나(이 시스템이 다루는
# "복잡도에 안 맞는 비싼 모델을 쓰지 마라" 원칙을 스스로에게도 적용), 이 계정의 IAM 사용자는 한동안
# Sonnet 계열만 호출 가능했고 일일 토큰 한도(ThrottlingException)에 자주 걸렸다. 2026-09-02 중 Haiku
# 접근 권한이 추가로 열려서, 이제 원래 설계 의도대로 되돌린다: 자주(중첩으로) 호출되는
# classify_complexity(판정 라우터)만 Haiku로 옮기고, Supervisor/research_agent/budget_agent 3개
# 실시간 핵심 역할은 서로 다른 Sonnet 버킷을 하나씩 전담한다 - 한 모델 ID에 여러 역할이 몰리지 않게
# 해서 Bedrock의 모델별 일일 토큰 한도 소진을 늦춘다(한도가 계정 전체가 아니라 모델 ID 단위로 걸리는
# 것으로 실측됨). 역할 구분 자체는 여전히 "추론 강도"(extended thinking budget, src/llm.py 참고)로도
# 함께 흉내낸다: Opus->extra, Sonnet->high, Haiku->low.
_MODEL_A = "global.anthropic.claude-sonnet-4-6"
_MODEL_B = "us.anthropic.claude-sonnet-4-6"
_MODEL_C = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
_HAIKU = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

MODEL_SUPERVISOR = os.getenv("COMPASS_MODEL_SUPERVISOR", _MODEL_C)
MODEL_RESEARCH = os.getenv("COMPASS_MODEL_RESEARCH", _MODEL_B)
MODEL_BUDGET = os.getenv("COMPASS_MODEL_BUDGET", _MODEL_A)
MODEL_ROUTER = os.getenv("COMPASS_MODEL_ROUTER", _HAIKU)  # classify_complexity 전용 - 판정만 하면 되므로 원래 의도대로 Haiku
# 오프라인 평가(run_eval.py judge)는 실시간 경로와 무관하고 채점 품질이 중요하므로 Sonnet 유지.
MODEL_JUDGE = os.getenv("COMPASS_MODEL_JUDGE", _MODEL_A)

# 접근 가능한 모델 전체 목록 - src/llm.py가 여기서 "primary 제외 나머지"를 폴백 후보로 삼는다.
# ThrottlingException/AccessDeniedException으로 primary 모델 호출이 실패하면, 같은 요청(같은
# 메시지·바인딩된 도구/구조화출력 설정)을 그대로 다음 후보 모델로 재시도한다(같은 계정 내 토큰
# 한도가 모델 ID 단위로 걸리는 것으로 실측됐으므로, 다른 모델은 별도 한도를 갖고 있어 유효한
# 회피책이다). 순서는 무관하다 - llm.py가 primary만 제외하고 나머지를 그대로 후보로 쓴다.
ALL_MODELS = [_MODEL_A, _MODEL_B, _MODEL_C, _HAIKU]

# 역할별 추론 강도(reasoning tier) - Opus->extra, Sonnet->high, Haiku->low 매핑을 그대로 사용.
# classify_complexity는 get_structured_llm(강제 tool-calling, thinking 항상 off)을 쓰므로 별도
# 추론 강도 설정이 필요 없다 - REASONING_ROUTER 같은 값은 두지 않는다(죽은 설정이 되므로).
# Supervisor는 thinking을 끈다(low) - 실측 결과 thinking이 켜져 있으면 라우팅 대신 티켓 내용을
# 직접 프롬프트로 분석해버리고 핸드오프 도구 호출 자체를 건너뛰는 사례가 나왔다(2026-09-03).
# Supervisor의 역할은 둘 중 하나로 보내는 단순 이진 결정이라 깊은 추론이 필요 없고, thinking이
# 오히려 "도구 호출 대신 말로 분석"하게 만드는 쪽으로 새는 것으로 보인다.
REASONING_SUPERVISOR = os.getenv("COMPASS_REASONING_SUPERVISOR", "low")
REASONING_RESEARCH = os.getenv("COMPASS_REASONING_RESEARCH", "high")
REASONING_BUDGET = os.getenv("COMPASS_REASONING_BUDGET", "high")
REASONING_JUDGE = os.getenv("COMPASS_REASONING_JUDGE", "extra")

# 그래프 실행 턴(스텝) 상한 - 라우팅이 꼬여 서브에이전트 간에 핑퐁하거나 도구 호출을 반복하는
# 경우, LangGraph 기본값(25)까지 그냥 흘러가게 두지 않고 도메인별 실제 필요량에 맞춰 명시적으로
# 제한한다. 2026-09-03 라이브 평가(evaluation/round1_report.json) 실측 tools_called 길이 기준:
#   - 단일 도메인(research_agent 단독 또는 budget_agent 단독) 흐름: 최대 3회 도구 호출 관찰
#     (예: retrieve_docs 2연속, get_token_budget 2연속) - 핸드오프 1 + (모델판단→도구실행) 반복 +
#     최종답변을 합치면 여유 있게 7스텝이면 충분하다.
#   - 복합 도메인(research_agent 판정 → budget_agent 예산확인) 흐름: 최대 8회 도구 호출 관찰
#     (예: id 15) - 두 도메인 스텝이 합쳐지므로 여유를 둬 15스텝으로 잡는다.
# Supervisor가 라우팅을 실제로 결정하기 전까지는 이번 턴이 단일/복합 중 무엇이 될지 알 수 없으므로,
# graph.ainvoke() 한 번에는 항상 복합 기준(RECURSION_LIMIT)을 적용한다 - 단일 도메인 값은 "이 정도면
# 충분하다"는 근거 기록용으로 남겨둔다.
RECURSION_LIMIT_SINGLE_DOMAIN = int(os.getenv("COMPASS_RECURSION_LIMIT_SINGLE_DOMAIN", "7"))
RECURSION_LIMIT = int(os.getenv("COMPASS_RECURSION_LIMIT", "15"))

MCP_SERVER_SCRIPT = str(ROOT / "src" / "mcp_server.py")
MCP_PYTHON = os.getenv("COMPASS_MCP_PYTHON") or __import__("sys").executable

TEAM_ID = os.getenv("COMPASS_TEAM_ID", "team_ai-enablement")
BUDGET_PERIOD = "2026-09"

TRACE_LOG_PATH = ROOT / "trace.jsonl"

RAG_TOP_K = int(os.getenv("COMPASS_RAG_TOP_K", "4"))

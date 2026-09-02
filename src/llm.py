from __future__ import annotations

from functools import cache
from typing import Literal

from langchain_aws import ChatBedrockConverse

from .config import AWS_REGION

# Opus는 여전히 접근 불가능하고, Sonnet 3개 버킷 + Haiku 2개 버킷만 실제로 호출 가능하다(config.py
# 참고). Opus 대응 역할은 모델을 바꾸는 대신 "추론 강도"(extended thinking budget)로 흉내낸다.
# Opus -> extra / Sonnet -> high or medium / Haiku -> low 매핑.
ReasoningTier = Literal["low", "medium", "high", "extra"]

_THINKING_BUDGET: dict[ReasoningTier, int | None] = {
    "low": None,  # thinking 비활성 - Haiku 대응, 구조화 출력(강제 tool-call)에도 필요
    "medium": 1024,
    "high": 2048,
    "extra": 4096,  # Opus 대응 - 판정(judge)처럼 깊은 추론이 필요한 1회성 작업 전용
}


@cache
def get_llm(model: str, tier: ReasoningTier = "high", temperature: float = 0.0) -> ChatBedrockConverse:
    """모델+티어 조합별로 하나씩만 생성해 재사용한다.

    주의: thinking(extended reasoning)이 켜지면 Bedrock이 temperature=1 강제 + 구조화 출력(forced
    tool-calling)을 신뢰할 수 없게 만든다. 그래서 "low" 티어(=구조화 출력이 필요한 classify_complexity 등)는
    thinking을 켜지 않는다. 나머지 티어는 일반 ReAct 도구 호출(강제 아님)에는 문제없이 thinking을 켠다.
    """
    budget = _THINKING_BUDGET[tier]
    if budget is None:
        return ChatBedrockConverse(model=model, region_name=AWS_REGION, temperature=temperature)
    return ChatBedrockConverse(
        model=model,
        region_name=AWS_REGION,
        additional_model_request_fields={"thinking": {"type": "enabled", "budget_tokens": budget}},
    )


@cache
def get_structured_llm(model: str, temperature: float = 0.0) -> ChatBedrockConverse:
    """구조화 출력(with_structured_output, 강제 tool-calling) 전용 - thinking을 절대 켜지 않는다."""
    return ChatBedrockConverse(model=model, region_name=AWS_REGION, temperature=temperature)

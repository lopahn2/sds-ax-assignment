from __future__ import annotations

import logging
from functools import cache
from typing import Any, Literal

from botocore.exceptions import ClientError
from langchain_aws import ChatBedrockConverse

from .config import ALL_MODELS, AWS_REGION

logger = logging.getLogger("agent_router")

# Opus는 여전히 접근 불가능하고, Sonnet 3개 버킷 + Haiku 1개 버킷만 실제로 호출 가능하다(config.py
# 참고). Opus 대응 역할은 모델을 바꾸는 대신 "추론 강도"(extended thinking budget)로 흉내낸다.
# Opus -> extra / Sonnet -> high or medium / Haiku -> low 매핑.
ReasoningTier = Literal["low", "medium", "high", "extra"]

_THINKING_BUDGET: dict[ReasoningTier, int | None] = {
    "low": None,  # thinking 비활성 - Haiku 대응, 구조화 출력(강제 tool-call)에도 필요
    "medium": 1024,
    "high": 2048,
    "extra": 4096,  # Opus 대응 - 판정(judge)처럼 깊은 추론이 필요한 1회성 작업 전용
}

_FALLBACK_CODES = {"ThrottlingException", "AccessDeniedException"}


class _FallbackChatBedrockConverse(ChatBedrockConverse):
    """primary 모델이 ThrottlingException/AccessDeniedException으로 실패하면, 같은 요청(같은
    메시지·bind_tools()로 바인딩된 도구·with_structured_output() 설정 전부 포함)을 그대로 다음
    후보 모델로 재시도한다.

    _generate만 오버라이드하고 나머지는 ChatBedrockConverse와 완전히 동일하므로,
    bind_tools()/with_structured_output() 등은 이 클래스 위에서도 그대로 동작한다 - 그 메서드들이
    돌려주는 바인딩된 Runnable은 실행 시점에 결국 이 인스턴스의 _generate를 호출하기 때문이다.

    boto3 자체 재시도(observed: "reached max retries: 4")가 이미 해당 모델 하나에 대해 소진된
    뒤에야 ClientError가 여기까지 올라오므로, 다음 모델로 넘어가는 것은 중복 재시도가 아니라
    실제로 새로운(그리고 한도가 분리된) 시도다."""

    fallback_candidates: tuple[ChatBedrockConverse, ...] = ()

    def _generate(self, messages: list, stop: list[str] | None = None, run_manager=None, **kwargs: Any):
        candidates: tuple[ChatBedrockConverse, ...] = (self, *self.fallback_candidates)
        last_error: ClientError | None = None
        for i, candidate in enumerate(candidates):
            try:
                if candidate is self:
                    return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                return ChatBedrockConverse._generate(candidate, messages, stop=stop, run_manager=run_manager, **kwargs)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                is_last = i == len(candidates) - 1
                if code not in _FALLBACK_CODES or is_last:
                    raise
                next_model = candidates[i + 1].model_id
                logger.warning("%s 실패(%s) - 다음 후보 모델(%s)로 재시도", candidate.model_id, code, next_model)
                last_error = e
        raise last_error  # pragma: no cover - 루프가 항상 return 또는 raise로 끝난다


def _build_with_fallback(primary: str, **construct_kwargs: Any) -> ChatBedrockConverse:
    fallback_models = [m for m in ALL_MODELS if m != primary]
    fallback_candidates = tuple(
        ChatBedrockConverse(model=m, region_name=AWS_REGION, **construct_kwargs) for m in fallback_models
    )
    return _FallbackChatBedrockConverse(
        model=primary, region_name=AWS_REGION, fallback_candidates=fallback_candidates, **construct_kwargs
    )


@cache
def get_llm(model: str, tier: ReasoningTier = "high", temperature: float = 0.0) -> ChatBedrockConverse:
    """모델+티어 조합별로 하나씩만 생성해 재사용한다. primary 모델이 일일 토큰 한도(Throttling)나
    권한 문제(AccessDenied)로 실패하면 같은 요청을 다른 모델로 자동 재시도한다(위 _FallbackChatBedrockConverse).

    주의: thinking(extended reasoning)이 켜지면 Bedrock이 temperature=1 강제 + 구조화 출력(forced
    tool-calling)을 신뢰할 수 없게 만든다. 그래서 "low" 티어(=구조화 출력이 필요한 classify_complexity 등)는
    thinking을 켜지 않는다. 나머지 티어는 일반 ReAct 도구 호출(강제 아님)에는 문제없이 thinking을 켠다.
    """
    budget = _THINKING_BUDGET[tier]
    if budget is None:
        return _build_with_fallback(model, temperature=temperature)
    return _build_with_fallback(
        model, additional_model_request_fields={"thinking": {"type": "enabled", "budget_tokens": budget}}
    )


@cache
def get_structured_llm(model: str, temperature: float = 0.0) -> ChatBedrockConverse:
    """구조화 출력(with_structured_output, 강제 tool-calling) 전용 - thinking을 절대 켜지 않는다."""
    return _build_with_fallback(model, temperature=temperature)

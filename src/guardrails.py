from __future__ import annotations

import re

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

# G1/G5 - 프롬프트 인젝션, 무단 상태변경 시도, 내부 로직/시스템 프롬프트 노출 요구, 타 팀 정보 요구
INJECTION_PATTERNS = [
    r"이전\s*(지시|지침|명령).{0,15}?(무시|잊)",
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"시스템\s*프롬프트",
    r"system\s*prompt",
    r"내부\s*(로직|코드|프롬프트|경로)",
    r"도구\s*스키마",
]

UNAUTHORIZED_MUTATION_PATTERNS = [
    r"예산\s*[을를]?\s*(무제한|임의|마음대로)",
    r"(잔액|예산)\s*[을를]?\s*(바꿔|변경|수정)",
    r"승인\s*없이",
]

CROSS_TEAM_PATTERNS = [
    r"(다른|옆|타)\s*팀",
    r"팀\s*[a-zA-Z0-9_\-]+\s*(예산|작업)",
]

REFUSAL_INJECTION = (
    "요청하신 방식으로는 처리할 수 없습니다. 시스템 프롬프트나 내부 도구 구현은 공개하지 않으며, "
    "이전 지시를 무시하라는 지시도 따르지 않습니다. 다만 6축 복잡도 루브릭처럼 공개된 판정 기준은 "
    "언제든 설명해 드릴 수 있고, 정상적인 파이프라인 추천·예산 조회는 계속 도와드릴 수 있습니다."
)

REFUSAL_MUTATION = (
    "예산은 승인 절차 없이 임의로 변경할 수 없습니다(G1). 정상적인 커밋은 항상 요약 카드를 먼저 보여드리고 "
    "명시적 승인을 받은 뒤에만 진행됩니다."
)

REFUSAL_CROSS_TEAM = "다른 팀의 예산이나 작업 이력은 조회 권한이 없어 보여드릴 수 없습니다. 본인 팀의 정보는 언제든 조회해 드릴 수 있습니다."


def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def check_input(text: str) -> str | None:
    """차단해야 하면 거절 메시지를, 정상이면 None을 반환한다."""
    if _match_any(INJECTION_PATTERNS, text):
        return REFUSAL_INJECTION
    if _match_any(UNAUTHORIZED_MUTATION_PATTERNS, text):
        return REFUSAL_MUTATION
    if _match_any(CROSS_TEAM_PATTERNS, text):
        return REFUSAL_CROSS_TEAM
    return None


class InputGuardrailMiddleware(AgentMiddleware):
    """모델 호출 전에 프롬프트 인젝션·무단 상태변경·타팀 조회 시도를 정규식으로 차단한다 (G1/G5).

    차단되면 handler(모델 호출)를 아예 생략하고 고정 거절 메시지를 즉시 반환한다.
    """

    def _refusal_for(self, request: ModelRequest) -> AIMessage | None:
        last_human = next(
            (m for m in reversed(request.messages) if m.__class__.__name__ == "HumanMessage"),
            None,
        )
        if last_human is None:
            return None
        refusal = check_input(str(last_human.content))
        return AIMessage(content=refusal) if refusal is not None else None

    def wrap_model_call(self, request: ModelRequest, handler):
        refusal = self._refusal_for(request)
        return refusal if refusal is not None else handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        refusal = self._refusal_for(request)
        return refusal if refusal is not None else await handler(request)


MASK_PATTERNS = [
    (re.compile(r"acct_[A-Za-z0-9]{4,}"), lambda m: "acct_" + "*" * 4 + m.group(0)[-4:]),
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), lambda m: "**** **** **** " + m.group(0)[-4:]),
]


def mask_sensitive(text: str) -> str:
    for pattern, repl in MASK_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class OutputGuardrailMiddleware(AgentMiddleware):
    """모델 응답에 남아있을 수 있는 계정 ID·카드번호류 문자열을 마스킹한다 (G5)."""

    @staticmethod
    def _mask_response(response: ModelResponse) -> ModelResponse:
        for msg in response.result:
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                msg.content = mask_sensitive(content)
            elif isinstance(content, list):
                # thinking이 켜진 응답은 content가 {"type": "text"|"reasoning_content", ...} 블록 리스트다.
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                        block["text"] = mask_sensitive(block["text"])
        return response

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return self._mask_response(handler(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return self._mask_response(await handler(request))

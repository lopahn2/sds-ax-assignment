from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AxisJudgment(BaseModel):
    """6축 복잡도 루브릭 판정 결과 (근거: data/docs/research/round4-router-rubric.md)"""

    a1_concurrency: bool = Field(description="A1 동시성·경합 - 병렬 요청이 같은 상태를 두고 경쟁하는가")
    a2_temporal_order: bool = Field(description="A2 시간적 순서 - 이벤트 순서·리플레이·수렴을 보장해야 하는가")
    a3_failure_invariant: bool = Field(description="A3 장애 불변식 - 크래시/재시작 후 지켜야 할 불변식이 명시되는가")
    a4_performance_target: bool = Field(description="A4 수치 성능 목표 - p95·처리량 같은 정량 목표가 있는가")
    a5_permission_matrix: bool = Field(description="A5 권한 조합 폭발 - 역할x리소스 매트릭스가 20셀 이상인가")
    a6_verification_mode: bool = Field(description="A6 검증 방식 - 순차 curl로 전 요구사항 검증이 불가능한가")
    rationale: str = Field(description="어떤 축이 왜 해당/비해당인지 한두 문장 근거")
    confidence: float = Field(ge=0.0, le=1.0, description="판정 확신도")

    @property
    def axis_count(self) -> int:
        return sum(
            [
                self.a1_concurrency,
                self.a2_temporal_order,
                self.a3_failure_invariant,
                self.a4_performance_target,
                self.a5_permission_matrix,
                self.a6_verification_mode,
            ]
        )

    @property
    def complexity_label(self) -> Literal["SIMPLE", "NORMAL", "COMPLEX"]:
        # policy/effort-tiering.md 결정 규칙: 0축 -> SIMPLE, 1축 -> NORMAL, 2축 이상 -> COMPLEX.
        # round4-router-rubric.md의 원 2단계(<=1축 SIMPLE / >=2축 COMPLEX) 원칙을 3단계로 확장한 것이다.
        # confidence가 낮을 때(<0.6)는 애매한 것으로 보고 한 단계 위 티어로 편향한다
        # (연구의 "불확실 시 COMPLEX로" 비대칭 오분류 비용 원칙을 3단계로 일반화).
        order: list[Literal["SIMPLE", "NORMAL", "COMPLEX"]] = ["SIMPLE", "NORMAL", "COMPLEX"]
        if self.axis_count >= 2:
            base = "COMPLEX"
        elif self.axis_count == 1:
            base = "NORMAL"
        else:
            base = "SIMPLE"
        if self.confidence < 0.6:
            idx = min(order.index(base) + 1, len(order) - 1)
            return order[idx]
        return base

    @property
    def pipeline_bucket(self) -> Literal["W-SIMPLE", "W-COMPLEX"]:
        """비용 산정용 2단계 버킷(원 연구가 실측한 두 파이프라인 구성) - NORMAL은 W-SIMPLE 쪽에 속한다."""
        return "W-COMPLEX" if self.complexity_label == "COMPLEX" else "W-SIMPLE"


class Context(BaseModel):
    doc_id: str
    text: str
    score: float | None = None


class TraceStep(BaseModel):
    step: str
    input: Any = None
    output: Any = None


class AnswerSchema(BaseModel):
    answer: str
    contexts: list[Context] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    assignment_summary: dict[str, Any] | None = None

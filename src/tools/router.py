from __future__ import annotations

from langchain_core.tools import tool

from .. import data_store
from ..config import MODEL_ROUTER
from ..llm import get_structured_llm
from ..schemas import AxisJudgment
from .pricing import EFFORT_RECIPES, predict_cost

# ---------------------------------------------------------------------------
# classify_complexity (판단형 도구 - 내부에서 저비용 라우터 모델을 호출)
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = """너는 개발 작업의 복잡도를 6축 루브릭으로 판정하는 라우터다.
아래 6개 축을 각각 참/거짓으로 판정하라. 애매하면 반드시 해당 축을 참(true)으로 판정해
COMPLEX 쪽으로 편향시켜라(불확실할 때의 오분류 비용이 SIMPLE 오분류보다 훨씬 크다).

A1 동시성·경합: 병렬 요청이 같은 상태를 두고 경쟁하는가(낙관적 잠금·정확히-하나-성공 요구 등)
A2 시간적 순서: 이벤트 순서·리플레이·다중 클라이언트 수렴을 보장해야 하는가(실시간 동기화 등)
A3 장애 불변식: 크래시/재시작 후 지켜야 할 원자성·무결성 조건이 명시되는가
A4 수치 성능 목표: p95·처리량 같은 구체적 수치 목표가 있는가
A5 권한 조합 폭발: 역할 3개 이상 x 행위별 상이한 규칙(20셀 이상)이 있는가
A6 검증 방식: 순차 curl로는 검증 불가능하고 다중 클라이언트/동시 요청 프로브가 필요한가

참고: A2(시간적 순서)가 있으면 검증을 위해 A6도 함께 해당되는 경우가 많다."""


@tool
def classify_complexity(task_description: str) -> dict:
    """개발 작업 설명(자연어 질문 또는 Jira 티켓 형태)을 6축 루브릭으로 SIMPLE/NORMAL/COMPLEX 3단계로 판정하고,
    그에 대응하는 구체적 워크플로우 안내(설계 강도·구현 강도·이유)와 카탈로그 기반 비용 예측을 함께 반환한다.
    유사 작업이 카탈로그에 없으면 비용 예측은 '불가'로 정직하게 반환된다. 예산 조회·일반 정책 질의처럼
    "만들 작업"을 설명하는 게 아닌 요청에는 이 도구를 쓰지 않는다."""
    llm = get_structured_llm(MODEL_ROUTER).with_structured_output(AxisJudgment)
    judgment: AxisJudgment = llm.invoke(
        [
            ("system", _CLASSIFY_SYSTEM_PROMPT),
            ("human", task_description),
        ]
    )
    matched = data_store.search_tasks(task_description, limit=1)
    cost_prediction = predict_cost(task_description, judgment.complexity_label)

    return {
        "axes": {
            "A1_concurrency": judgment.a1_concurrency,
            "A2_temporal_order": judgment.a2_temporal_order,
            "A3_failure_invariant": judgment.a3_failure_invariant,
            "A4_performance_target": judgment.a4_performance_target,
            "A5_permission_matrix": judgment.a5_permission_matrix,
            "A6_verification_mode": judgment.a6_verification_mode,
        },
        "axis_count": judgment.axis_count,
        "complexity_label": judgment.complexity_label,
        "workflow_recipe": EFFORT_RECIPES[judgment.complexity_label],
        "cost_prediction": cost_prediction,
        "recommended_pipeline": judgment.pipeline_bucket,
        "confidence": judgment.confidence,
        "rationale": judgment.rationale,
        "cited_doc_ids": ["research/round4-router-rubric.md", "policy/effort-tiering.md"],
        "matched_catalog_task": matched[0]["task_id"] if matched else None,
    }

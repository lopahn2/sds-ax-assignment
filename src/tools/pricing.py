from __future__ import annotations

from .. import data_store

# 판정 라벨을 "설계에는 얼마나, 구현에는 얼마나"라는 실행 가능한 안내로 옮기는 레시피.
# policy/effort-tiering.md에 정의된 이 서비스 자체 정책(원 연구의 2단계 SIMPLE/COMPLEX 원칙을 3단계로 확장)을
# 그대로 코드화했다. 라벨(SIMPLE/NORMAL/COMPLEX)만 말하고 끝내면 사용자가 "그래서 실제로 어떻게 진행해야
# 하는데?"를 알 수 없으므로, 항상 이 구체 정보를 함께 반환한다.
EFFORT_RECIPES = {
    "SIMPLE": {
        "design_effort": "medium",
        "implementation_effort": "medium",
        "why": "간단한 작업은 설계·구현 모두 중간 강도로 충분하다 - 과한 추론은 비용만 늘린다.",
    },
    "NORMAL": {
        "design_effort": "high",
        "implementation_effort": "medium",
        "why": "설계 단계에서 확실히 방향을 잡아두면, 구현은 중간 강도로도 그 설계를 충실히 따라갈 수 있다.",
    },
    "COMPLEX": {
        "design_effort": "medium",
        "implementation_effort": "high",
        "why": "얇은 설계라도 구현 단계의 강한 추론이 시행착오를 줄여 되레 저렴하고 안전하다(실측: R2·R3).",
    },
}


def predict_cost(task_description: str, complexity_label: str, top_k: int = 3, min_score: int = 2) -> dict:
    """카탈로그에 쌓인 실측/추정 비용 데이터를 근거로 유사 작업 기반 비용을 예측한다.
    키워드 중복이 min_score 미만이면(=근거로 삼을 만큼 비슷한 작업이 없으면) 정직하게 '예측 불가'를 반환한다
    - 근거 없는 숫자를 만들어내지 않는다(G4)."""
    similar = data_store.search_tasks(task_description, limit=top_k, min_score=min_score)
    if not similar:
        return {
            "available": False,
            "message": "RAG/카탈로그에서 유사한 과거 작업을 찾지 못해 비용 산출이 현재 어렵습니다.",
        }
    same_tier = [t for t in similar if t.get("complexity_label") == complexity_label]
    basis = same_tier or similar
    costs = [t["estimated_cost"] for t in basis]
    times = [t["estimated_time_min"] for t in basis if isinstance(t.get("estimated_time_min"), (int, float))]
    result = {
        "available": True,
        "estimated_cost_range_usd": [round(min(costs), 2), round(max(costs), 2)],
        "based_on_tasks": [{"task_id": t["task_id"], "name": t["name"], "cost": t["estimated_cost"]} for t in basis],
        "same_tier_match": bool(same_tier),
        "note": (
            f"카탈로그 유사 작업 {len(basis)}건 기반 추정"
            if same_tier
            else f"동일 복잡도 티어의 유사 작업은 없어, 가장 가까운 유사 작업 {len(basis)}건으로 참고 추정(신뢰도 낮음)"
        ),
    }
    if times:
        result["estimated_time_range_min"] = [min(times), max(times)]
    return result

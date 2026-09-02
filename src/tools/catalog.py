from __future__ import annotations

from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .. import data_store
from .pricing import EFFORT_RECIPES, predict_cost

# ---------------------------------------------------------------------------
# 1. search_similar_tasks
# ---------------------------------------------------------------------------


@tool
def search_similar_tasks(query: str) -> list[dict]:
    """과거·카탈로그의 유사 작업을 이름/카테고리/태그 기준으로 검색한다. 실측 이력(times_completed, avg_actual_cost)도 함께 반환한다."""
    return data_store.search_tasks(query)


# ---------------------------------------------------------------------------
# 2. get_task_record
# ---------------------------------------------------------------------------


@tool
def get_task_record(task_id: str, config: RunnableConfig) -> dict:
    """작업 카탈로그에서 특정 task_id의 상세 정보(축 판정·예상비용·실측이력)를 조회한다."""
    task = data_store.get_task(task_id)
    if task is None:
        return {"status": "NOT_FOUND", "message": f"작업 ID {task_id} 를 카탈로그에서 찾을 수 없습니다."}
    thread_id = config.get("configurable", {}).get("thread_id", "default")
    data_store.touch_task(thread_id, task_id)
    return task


# ---------------------------------------------------------------------------
# 3. compare_pipelines
# ---------------------------------------------------------------------------


class CompareItem(BaseModel):
    label: str = Field(description="비교표에 표시할 이름")
    task_id: str | None = Field(default=None, description="카탈로그에 있는 기존 작업이면 그 task_id")
    task_description: str | None = Field(
        default=None,
        description=(
            "카탈로그에 없는 가상의 옵션이면 그 작업을 설명하는 자연어 문장 - classify_complexity를 먼저 "
            "호출했을 때 넘긴 것과 같은 task_description을 그대로 쓴다. 이 문장으로 카탈로그 유사도 기반 "
            "비용을 내부에서 계산하므로, 비용 숫자를 직접 넘기지 않는다."
        ),
    )
    complexity_label: Literal["SIMPLE", "NORMAL", "COMPLEX"] | None = Field(
        default=None, description="카탈로그에 없는 가상의 옵션이면 classify_complexity 결과의 라벨"
    )


def _sort_cost(row: dict) -> float | None:
    if isinstance(row.get("estimated_cost"), (int, float)):
        return row["estimated_cost"]
    prediction = row.get("cost_prediction")
    if prediction and prediction.get("available"):
        lo, hi = prediction["estimated_cost_range_usd"]
        return (lo + hi) / 2
    return None


@tool
def compare_pipelines(items: list[CompareItem]) -> dict:
    """2~3개의 파이프라인/작업 옵션을 비용·시간·복잡도·설계구현 강도 기준으로 비교표로 만든다.
    기존 카탈로그 task_id는 실측 비용을 그대로 쓰고, 카탈로그에 없는 가상 옵션은 task_description으로
    카탈로그 유사 작업을 검색해 비용을 예측한다(predict_cost와 동일한 로직) - 비용을 직접 지어내
    넘기는 것은 허용하지 않는다(G4). 유사 작업이 없으면 해당 옵션은 비용 '예측 불가'로 정직하게 표시된다."""
    rows = []
    for item in items:
        if item.task_id:
            t = data_store.get_task(item.task_id)
            if t is None:
                rows.append({"label": item.label, "task_id": item.task_id, "error": "NOT_FOUND"})
                continue
            rows.append(
                {
                    "label": item.label,
                    "task_id": t["task_id"],
                    "complexity_label": t["complexity_label"],
                    "workflow_recipe": EFFORT_RECIPES.get(t["complexity_label"]),
                    "estimated_cost": t["estimated_cost"],
                    "estimated_time_min": t["estimated_time_min"],
                    "cost_basis": "catalog_actual",
                }
            )
        elif item.task_description and item.complexity_label:
            prediction = predict_cost(item.task_description, item.complexity_label)
            rows.append(
                {
                    "label": item.label,
                    "complexity_label": item.complexity_label,
                    "workflow_recipe": EFFORT_RECIPES.get(item.complexity_label),
                    "cost_prediction": prediction,
                    "cost_basis": "catalog_similarity" if prediction["available"] else "unavailable",
                }
            )
        else:
            rows.append(
                {
                    "label": item.label,
                    "error": "MISSING_DESCRIPTION",
                    "message": "카탈로그에 없는 옵션은 task_description과 complexity_label이 필요합니다 (classify_complexity를 먼저 호출하세요).",
                }
            )

    priced = [(r["label"], _sort_cost(r)) for r in rows if _sort_cost(r) is not None]
    lowest = min(priced, key=lambda x: x[1]) if priced else None
    return {"comparison": rows, "lowest_cost_label": lowest[0] if lowest else None}

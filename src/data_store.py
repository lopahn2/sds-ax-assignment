from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

from .config import DATA_DIR


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _save_atomic(name: str, data: dict) -> None:
    path = DATA_DIR / name
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---- 카탈로그 ----


def list_tasks() -> list[dict]:
    return _load("tasks.json")["tasks"]


def get_task(task_id: str) -> dict | None:
    return next((t for t in list_tasks() if t["task_id"] == task_id), None)


def search_tasks(query: str, limit: int = 5, min_score: int = 1) -> list[dict]:
    """이름·카테고리·태그 키워드 중복도로 유사 작업을 찾는다. 결과 각 항목에 match_score를 얹어 반환한다
    (호출자가 신뢰도를 스스로 판단할 수 있도록 - 예: 비용 예측처럼 신뢰도가 중요한 곳은 min_score를 올려 재검색).
    겹치는 단어가 하나도 없으면 빈 리스트를 반환한다 - "유사 작업 없음"을 정직하게 나타내는 신호다."""
    q_tokens = [t for t in query.lower().replace(",", " ").split() if t]
    scored = []
    for t in list_tasks():
        haystack = " ".join([t["name"], t["category"], " ".join(t.get("tags", []))]).lower()
        score = sum(1 for tok in q_tokens if tok in haystack)
        if score >= min_score:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return [{**t, "match_score": s} for s, t in scored[:limit]]


# ---- 예산 ----


def get_budget() -> dict:
    return _load("token_budget.json")


# ---- 커밋(상태 변경, 원자적) ----


class LedgerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _register_adhoc_task(task_id: str, estimated_cost: float, pipeline: str) -> dict:
    """카탈로그에 없는 신규 작업을 최소 정보로 등록한다.
    (모델이 카탈로그 ID 대신 자유 텍스트를 넘겼을 때도 assignments의 참조 무결성이 깨지지 않도록 하는 안전장치.)"""
    catalog = _load("tasks.json")
    new_task = {
        "task_id": task_id,
        "name": task_id,
        "category": "미분류(신규)",
        "axes": None,
        "axis_count": None,
        "complexity_label": "COMPLEX" if pipeline == "W-COMPLEX" else "SIMPLE",
        "recommended_pipeline": pipeline,
        "estimated_cost": estimated_cost,
        "estimated_time_min": None,
        "estimation_basis": "commit 시점에 자동 등록된 신규 작업 - 사전 카탈로그 항목 아님",
        "times_completed": 0,
        "avg_actual_cost": None,
        "doc_id": "research/round4-router-rubric.md",
        "tags": ["신규", "자동등록"],
    }
    catalog["tasks"].append(new_task)
    catalog["_meta"]["count"] = len(catalog["tasks"])
    _save_atomic("tasks.json", catalog)
    return new_task


def commit_assignment(task_id: str, committed_cost: float, pipeline: str) -> dict:
    """예산을 원자적으로 차감하고 assignment 를 생성한다. 한도를 넘으면 아무 것도 반영하지 않고 예외를 던진다."""
    budget = _load("token_budget.json")
    assignments = _load("assignments.json")

    task = get_task(task_id)
    if task is None:
        # 카탈로그에 없는 신규(ad-hoc) 작업 - 참조 무결성이 깨지지 않도록 최소 정보로 즉석 등록한다.
        task = _register_adhoc_task(task_id, committed_cost, pipeline)
    if committed_cost > budget["limits"]["single_task_limit"]:
        raise LedgerError("SINGLE_TASK_LIMIT_EXCEEDED", "1건 한도를 초과했습니다.")
    if committed_cost > budget["balance"]:
        raise LedgerError("INSUFFICIENT_BALANCE", "팀 잔액이 부족합니다.")

    new_balance = round(budget["balance"] - committed_cost, 2)
    new_spent = round(budget["monthly_spent"] + committed_cost, 2)

    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    seq = len(assignments["assignments"]) + 1
    assignment_id = f"ASG-{dt.datetime.now():%Y%m%d}-{seq:03d}"
    new_assignment = {
        "assignment_id": assignment_id,
        "team_id": budget["team_id"],
        "task_id": task_id,
        "task_name": task.get("name", task_id),
        "pipeline": pipeline,
        "committed_cost": committed_cost,
        "actual_cost": None,
        "committed_at": now,
        "status": "IN_PROGRESS",
        "timeline": [
            {"stage": "RECOMMENDED", "at": now},
            {"stage": "APPROVED", "at": now},
            {"stage": "IN_PROGRESS", "at": now},
        ],
    }

    budget_backup = json.dumps(budget)
    try:
        budget["balance"] = new_balance
        budget["monthly_spent"] = new_spent
        _save_atomic("token_budget.json", budget)
        assignments["assignments"].append(new_assignment)
        _save_atomic("assignments.json", assignments)
    except Exception:
        _save_atomic("token_budget.json", json.loads(budget_backup))
        raise

    return new_assignment

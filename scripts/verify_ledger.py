"""
데이터·원장 정합성 검증 스크립트

두 가지를 검증한다.
  1) 정적 정합성 : 카탈로그·문서·assignment·예산·이벤트 규칙이 서로 어긋나지 않는가
  2) 원장 불변식 : 이번 예산 기간의 유효 assignment 커밋 합계 == token_budget.monthly_spent
                   (커밋 실패 시 예산이 원상 복구되었는지 판정하는 기준)

사용:
    python scripts/verify_ledger.py              # 정적 검증
    python scripts/verify_ledger.py --snapshot   # 현재 상태를 스냅샷으로 저장
    python scripts/verify_ledger.py --compare    # 스냅샷과 현재 상태 비교 (커밋 실패 후 롤백 검증)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DOCS = DATA / "docs"
SNAPSHOT = ROOT / "scripts" / ".ledger_snapshot.json"

BUDGET_PERIOD = "2026-09"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def check_static() -> list[str]:
    errors: list[str] = []
    tasks = load("tasks.json")
    budget = load("token_budget.json")
    assignments = load("assignments.json")

    items = tasks["tasks"]
    by_id = {t["task_id"]: t for t in items}

    # 1. 카탈로그 개수 선언과 실제 일치
    if tasks["_meta"]["count"] != len(items):
        errors.append(f"tasks._meta.count={tasks['_meta']['count']} != 실제 {len(items)}")

    # 2. task_id 중복 없음
    if len(by_id) != len(items):
        errors.append("tasks.json 에 중복된 task_id 가 있습니다")

    # 3. doc_id 로 연결된 문서가 실제 존재
    for t in items:
        doc_id = t.get("doc_id")
        if doc_id and not (DOCS / doc_id).exists():
            errors.append(f"{t['task_id']}: 문서 {doc_id} 없음")

    # 4. 문서 frontmatter 의 doc_id 가 실제 경로와 일치
    for md in sorted(DOCS.rglob("*.md")):
        rel = md.relative_to(DOCS).as_posix()
        text = md.read_text(encoding="utf-8")
        head = text.split("---")[1] if text.startswith("---") else ""
        declared = next(
            (line.split(":", 1)[1].strip() for line in head.splitlines() if line.startswith("doc_id:")),
            None,
        )
        if declared != rel:
            errors.append(f"{rel}: frontmatter doc_id='{declared}' 가 경로와 불일치")

    # 5. assignment가 참조하는 작업이 카탈로그에 존재하고 상태·타임라인이 정합
    valid_stages = set(assignments["pipeline_stages"])
    for a in assignments["assignments"]:
        if a["task_id"] not in by_id:
            errors.append(f"{a['assignment_id']}: 존재하지 않는 작업 {a['task_id']}")
        if a["status"] not in valid_stages:
            errors.append(f"{a['assignment_id']}: 알 수 없는 상태 {a['status']}")
        stages = [t["stage"] for t in a["timeline"]]
        if stages[-1] != a["status"]:
            errors.append(f"{a['assignment_id']}: timeline 마지막 단계({stages[-1]}) != status({a['status']})")

    # 6. 원장 불변식 - 이번 예산 기간 유효 assignment 커밋 합계 == monthly_spent
    committed = round(
        sum(
            a["committed_cost"]
            for a in assignments["assignments"]
            if a["status"] != "CANCELLED" and a["committed_at"].startswith(BUDGET_PERIOD)
        ),
        2,
    )
    if committed != budget["monthly_spent"]:
        errors.append(
            f"원장 불변식 위반: assignment 커밋 합계 ${committed:,.2f} != token_budget.monthly_spent ${budget['monthly_spent']:,.2f}"
        )

    # 7. 가드레일 시나리오가 성립하는 수치인지 (test_queries.csv edge 항목 전제)
    balance = budget["balance"]
    remaining = round(budget["monthly_budget"] - budget["monthly_spent"], 2)
    limit = budget["limits"]["single_task_limit"]

    scenarios = [
        ("잔액 부족", by_id["T-2002"]["estimated_cost"], lambda v: v > balance),
        ("예산 초과·잔액 충분", by_id["T-2001"]["estimated_cost"], lambda v: remaining < v <= balance),
        ("1건 한도 초과", by_id["T-5001"]["estimated_cost"], lambda v: v > limit),
    ]
    for label, price, ok in scenarios:
        if not ok(price):
            errors.append(
                f"시나리오 전제 붕괴 - {label}: 비용 ${price:,.2f} (잔액 ${balance:,.2f} / 예산잔여 ${remaining:,.2f} / 한도 ${limit:,.2f})"
            )

    print(
        f"작업 카탈로그 {len(items)}종 / 문서 {len(list(DOCS.rglob('*.md')))}건 / assignment {len(assignments['assignments'])}건"
    )
    print(f"팀 잔액 ${balance:,.2f} · 월예산 잔여 ${remaining:,.2f} · 1건 한도 ${limit:,.2f}")
    return errors


def state() -> dict:
    budget = load("token_budget.json")
    assignments = load("assignments.json")
    return {
        "balance": budget["balance"],
        "monthly_spent": budget["monthly_spent"],
        "assignment_ids": sorted(a["assignment_id"] for a in assignments["assignments"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true", help="현재 상태를 스냅샷으로 저장")
    ap.add_argument("--compare", action="store_true", help="스냅샷과 현재 상태를 비교 (롤백 검증)")
    args = ap.parse_args()

    if args.snapshot:
        SNAPSHOT.write_text(json.dumps(state(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"스냅샷 저장: {SNAPSHOT.relative_to(ROOT)}")
        return 0

    if args.compare:
        if not SNAPSHOT.exists():
            print("스냅샷이 없습니다. --snapshot 을 먼저 실행하세요.")
            return 2
        before = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        after = state()
        diffs = []
        for key in ("balance", "monthly_spent"):
            if before[key] != after[key]:
                diffs.append(f"{key}: {before[key]:,} -> {after[key]:,}")
        new_assignments = sorted(set(after["assignment_ids"]) - set(before["assignment_ids"]))
        if new_assignments:
            diffs.append(f"신규 assignment: {', '.join(new_assignments)}")
        if diffs:
            print("변경 감지 (커밋 실패 케이스라면 위반):")
            for d in diffs:
                print("  -", d)
            return 1
        print("변경 없음 - 팀 예산·assignment 가 모두 원상 유지되었습니다.")
        return 0

    errors = check_static()
    if errors:
        print(f"\n검증 실패 {len(errors)}건:")
        for e in errors:
            print("  ✗", e)
        return 1
    print("\n모든 정합성 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())

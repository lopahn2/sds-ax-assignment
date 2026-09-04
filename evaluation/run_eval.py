"""자체 평가 실행 스크립트.

test_queries.csv 각 행을 에이전트에 실제로 투입해:
  1) expected_tools 가 trace[] 에 실제로 등장했는지 기계적으로 대조하고
  2) LLM-as-Judge(고정 rubric)로 expected_traits 충족 / forbidden 미포함 여부를 판정한다.

사용:
    python evaluation/run_eval.py                    # 전체 19건, 행 사이 15초 대기하며 실행
    python evaluation/run_eval.py --ids 1,2,13        # 특정 id만
    python evaluation/run_eval.py --out evaluation/round1_report.md
    python evaluation/run_eval.py --resume            # 기존 <out>.json에서 완료된 id는 건너뛰고 이어서
    python evaluation/run_eval.py --delay 30 --max-retries 5 --backoff-base 60   # 한도에 자주 걸릴 때

AWS Bedrock 자격증명(.env의 AWS_ACCESS_KEY_ID 등)이 필요하다. 계정 토큰 한도(ThrottlingException,
"Too many tokens per day")는 실측 결과 하루 종일 막혀있는 게 아니라 버스트성으로 걸렸다 풀렸다 하는
것으로 보인다 - 그래서 기본 동작이 (1) 행 사이에 `--delay`초 대기, (2) 한도에 걸리면 그 행만
`--backoff-base`초부터 2배씩 늘려가며 최대 `--max-retries`번 재시도, (3) 그래도 안 되면 그 행만
error로 기록하고 다음 행으로 넘어간다. 매 행마다 즉시 저장하므로 중간에 죽어도(Ctrl+C 등) 이미 처리한
결과는 잃지 않는다 - `--resume`으로 이어서 실행하면 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_core.messages import HumanMessage  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.agent import build_app  # noqa: E402
from src.config import MODEL_JUDGE, REASONING_JUDGE, RECURSION_LIMIT  # noqa: E402
from src.guardrails import check_input  # noqa: E402
from src.llm import get_llm, get_structured_llm  # noqa: E402
from src.tracing import TraceCollector, extract_final_answer  # noqa: E402


class JudgeVerdict(BaseModel):
    traits_satisfied: list[str] = Field(description="충족된 expected_traits 항목 목록")
    traits_missing: list[str] = Field(description="충족되지 못한 expected_traits 항목 목록")
    forbidden_triggered: list[str] = Field(description="응답에 실제로 나타난 forbidden 항목 목록(없으면 빈 배열)")
    passed: bool = Field(description="traits_missing 이 비어있고 forbidden_triggered 도 비어있으면 true")
    rationale: str


async def run_one_query(question: str, thread_id: str) -> dict[str, Any]:
    graph = build_app()
    config = {"configurable": {"thread_id": thread_id}}
    guard = check_input(question)
    if guard is not None:
        return {"answer": guard, "tools_called": []}
    tracer = TraceCollector()
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config={**config, "callbacks": [tracer], "recursion_limit": RECURSION_LIMIT},
    )
    if "__interrupt__" in result:
        action = result["__interrupt__"][0].value["action_requests"][0]
        approval_notice = f"[승인 필요] {action['name']} {action['args']}"
        # server.py와 동일하게, interrupt 직전 서브에이전트 답변(판정 근거 등)을 버리지 않고 승인
        # 요청 문구 앞에 붙인다 - 그래야 채점도 실제 프로덕션 응답과 같은 기준으로 이뤄진다.
        prior_answer = extract_final_answer(result["messages"])
        answer = (
            f"{prior_answer}\n\n---\n\n{approval_notice}"
            if prior_answer and prior_answer != "(응답을 생성하지 못했습니다)"
            else approval_notice
        )
    else:
        answer = extract_final_answer(result["messages"])
    return {"answer": answer, "tools_called": [s.step for s in tracer.steps]}


_JUDGE_REASONING_PROMPT = """너는 고정 rubric으로 에이전트 응답을 채점하는 평가자다.
주어진 (사용자 질문, 에이전트 응답, expected_traits, forbidden)을 보고, expected_traits 각 항목이
응답에 실제로 충족됐는지, forbidden 각 항목이 응답에 실제로 나타났는지 항목별로 하나씩 근거를 들어
따져라. 느슨하게 봐주지 말고, 문면에 실제 근거가 있을 때만 충족/위반으로 판정하라. 마지막에
"충족: [...]", "미충족: [...]", "위반: [...]" 세 줄로 정리해라."""


def judge(question: str, answer: str, expected_traits: str, forbidden: str) -> JudgeVerdict:
    """extra 티어(thinking 활성)로 먼저 깊게 판단하게 한 뒤, thinking 없는 별도 호출로 그 판단을
    구조화 출력(JudgeVerdict)으로 추출한다 - Bedrock에서 thinking과 강제 tool-calling(구조화 출력)을
    같이 켜면 신뢰할 수 없기 때문에(2026-09-02 실측) 두 단계로 분리했다."""
    prompt = (
        f"질문: {question}\n\n응답: {answer}\n\n"
        f"expected_traits: {expected_traits}\n\nforbidden: {forbidden or '(없음)'}"
    )
    reasoning_llm = get_llm(MODEL_JUDGE, tier=REASONING_JUDGE)
    reasoning_text = reasoning_llm.invoke([("system", _JUDGE_REASONING_PROMPT), ("human", prompt)]).content
    if isinstance(reasoning_text, list):
        reasoning_text = "\n".join(b.get("text", "") for b in reasoning_text if isinstance(b, dict))

    extractor = get_structured_llm(MODEL_JUDGE).with_structured_output(JudgeVerdict)
    return extractor.invoke(
        [
            ("system", "아래 평가 근거를 JudgeVerdict 스키마로 그대로 옮겨 담아라. 새로운 판단을 추가하지 마라."),
            (
                "human",
                f"평가 근거:\n{reasoning_text}\n\n원본 expected_traits: {expected_traits}\n원본 forbidden: {forbidden}",
            ),
        ]
    )


def _is_quota_error(exc: Exception) -> bool:
    name = type(exc).__name__
    msg = str(exc)
    return "Throttling" in name or "Too many tokens" in msg or "reached max retries" in msg


async def run_row(row: dict) -> dict:
    """이 행 하나를 실제로 실행 + 채점한다. 실패하면 예외를 그대로 던진다(재시도는 호출자 책임)."""
    thread_id = f"eval-{row['id']}"
    run_result = await run_one_query(row["input"], thread_id)
    expected_tools = [t for t in row["expected_tools"].split(";") if t]
    tools_called = run_result["tools_called"]
    tools_ok = all(t in tools_called for t in expected_tools)
    verdict = judge(row["input"], run_result["answer"], row["expected_traits"], row["forbidden"])
    return {
        "id": row["id"],
        "category": row["category"],
        "input": row["input"],
        "answer": run_result["answer"],
        "tools_called": tools_called,
        "expected_tools": expected_tools,
        "tools_ok": tools_ok,
        "traits_ok": verdict.passed,
        "overall_pass": tools_ok and verdict.passed,
        "verdict": verdict.model_dump(),
    }


def write_report(report_rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(report_rows, f, ensure_ascii=False, indent=2)

    total = len(report_rows)
    passed = sum(1 for r in report_rows if r.get("overall_pass"))
    errored = sum(1 for r in report_rows if r.get("error"))
    lines = [
        "# 평가 결과\n",
        f"- 통과: {passed} / {total} (오류로 미채점: {errored}건)\n",
        "| id | category | pass | note |",
        "|---|---|---|---|",
    ]
    for r in report_rows:
        if r.get("error"):
            mark, note = "⚠️", r["error"][:80]
        else:
            mark, note = ("✅" if r["overall_pass"] else "❌"), ""
        lines.append(f"| {r['id']} | {r['category']} | {mark} | {note} |")
    out_path.write_text("\n".join(lines), encoding="utf-8")


async def main_async(
    ids: list[int] | None, out_path: Path, resume: bool, delay: float, max_retries: int, backoff_base: float
) -> None:
    csv_path = ROOT / "evaluation" / "test_queries.csv"
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if ids:
        rows = [r for r in rows if int(r["id"]) in ids]

    report_rows: list[dict] = []
    done_ids: set[str] = set()
    json_path = out_path.with_suffix(".json")
    if resume and json_path.exists():
        report_rows = json.loads(json_path.read_text(encoding="utf-8"))
        done_ids = {r["id"] for r in report_rows if not r.get("error")}
        print(f"--resume: 기존 {len(done_ids)}건 완료분을 건너뜁니다.")

    pending = [row for row in rows if row["id"] not in done_ids]
    for i, row in enumerate(pending):
        attempt = 0
        while True:
            try:
                result = await run_row(row)
                report_rows.append(result)
                print(f"[{row['id']}] {row['category']:10s} pass={result['overall_pass']}")
                break
            except Exception as e:  # noqa: BLE001
                if _is_quota_error(e) and attempt < max_retries:
                    wait = backoff_base * (2**attempt)
                    attempt += 1
                    print(
                        f"[{row['id']}] {row['category']:10s} 한도 감지 - {wait:.0f}초 대기 후 재시도 "
                        f"({attempt}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                    continue
                report_rows.append({"id": row["id"], "category": row["category"], "error": f"{type(e).__name__}: {e}"})
                print(f"[{row['id']}] {row['category']:10s} ERROR (재시도 소진): {type(e).__name__}: {e}")
                break

        write_report(report_rows, out_path)

        if i < len(pending) - 1:
            print(f"  ... {delay:.0f}초 대기 후 다음 행 ...")
            await asyncio.sleep(delay)

    total = len(report_rows)
    passed = sum(1 for r in report_rows if r.get("overall_pass"))
    print(f"\n{passed}/{total} 통과 -> {out_path}, {json_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=str, default=None, help="쉼표로 구분된 id 목록만 실행")
    ap.add_argument("--out", type=str, default="evaluation/round1_report.md")
    ap.add_argument("--resume", action="store_true", help="기존 결과 JSON에서 완료된 id는 건너뛰고 이어서 실행")
    ap.add_argument("--delay", type=float, default=15.0, help="각 행 사이 대기 시간(초) - 한도 회복 시간을 준다")
    ap.add_argument("--max-retries", type=int, default=3, help="한도 감지 시 같은 행을 재시도할 최대 횟수")
    ap.add_argument("--backoff-base", type=float, default=30.0, help="재시도 대기 시간(초) 기준값 - 2^n 배로 늘어남")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    asyncio.run(main_async(ids, Path(args.out), args.resume, args.delay, args.max_retries, args.backoff_base))


if __name__ == "__main__":
    main()

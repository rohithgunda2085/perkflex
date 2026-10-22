"""Runs the saved perk-advisor cases (tests/fixtures/advisor_cases.json) against the REAL model and reports what happened.

    cd backend
    ../../.venv/bin/python scripts/eval_advisor.py                 # every case, once
    ../../.venv/bin/python scripts/eval_advisor.py --repeat 3      # the model varies, so repeat to see how much
    ../../.venv/bin/python scripts/eval_advisor.py --case maya-unused-bag-and-extra-seat --show
    ../../.venv/bin/python scripts/eval_advisor.py --report evals/today.json --compare evals/last-good.json --min-ai-rate 0.8
    ../../.venv/bin/python scripts/eval_advisor.py --offline       # rules-only answers: no model, no cost, fine for CI

Needs the Bedrock settings from .env (AWS_BEARER_TOKEN_BEDROCK or an AWS role, BEDROCK_MODEL_ID, AWS_REGION). It costs a
little: roughly one model conversation per case per repeat. Cases with no choice to make (check-in closed, nothing to
pick) never call the model, so they cost nothing.

Exit code: 0 when every expectation held and the thresholds were met; 1 otherwise; 2 when no case matched.
  --min-ai-rate   fail when fewer than this share of model-backed runs were answered by the model itself (not the fallback)
  --report FILE   save every run as JSON (case, source, picks, summary, ms, problems)
  --compare FILE  print which cases changed since a saved report, and the change in the ai rate
  --offline       judge the rules-only answers against each case's "fallback" expectations instead of calling the model

Reading the report:
  source  ai = the model's answer passed validation; fallback = the rules-only answer was used (the reason is logged).
  check   OK, or what broke an expectation (see "live" in each case). The safety checks always apply.
Things to look at after a run: a low "ai" rate (the prompt or validator is too strict), repeated fallback reasons,
summaries that sound off (use --show), and picks that differ between repeats of the same case.
"""

import argparse
import json
import logging
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.advisor.advisor import advise, deterministic_advice  # noqa: E402
from app.advisor.types import AdviceRequest  # noqa: E402
from app.config import get_settings  # noqa: E402
from tests.advisor_support import context_for, load_cases, problems  # noqa: E402


def compare(now: dict, before: dict) -> None:
    """Prints what changed since an earlier report: cases that started or stopped passing, and the ai rate."""
    def status(rep: dict) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for run in rep["runs"]:
            out[run["case"]] = out.get(run["case"], True) and not run["problems"]
        return out

    a, b = status(before), status(now)
    print(f"\ncompared with {before.get('when', '?')} ({before.get('mode', '?')}, model {before.get('model')})")
    changed = False
    for case in sorted(set(a) | set(b)):
        if case not in a:
            print(f"  new case: {case} ({'pass' if b[case] else 'FAIL'})")
            changed = True
        elif case not in b:
            print(f"  not run now: {case}")
        elif a[case] != b[case]:
            print(f"  {case}: {'pass' if a[case] else 'fail'} -> {'pass' if b[case] else 'FAIL'}")
            changed = True
    if before.get("aiRate") is not None and now.get("aiRate") is not None:
        print(f"  ai rate {before['aiRate']:.0%} -> {now['aiRate']:.0%}")
    if not changed:
        print("  no case changed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("--repeat", type=int, default=1, help="runs per case")
    ap.add_argument("--show", action="store_true", help="print each summary and reason")
    ap.add_argument("--offline", action="store_true", help="rules-only answers, judged by each case's fallback expectations")
    ap.add_argument("--report", help="write the results of this run to this JSON file")
    ap.add_argument("--compare", help="compare with a report saved earlier")
    ap.add_argument("--min-ai-rate", type=float, default=0.0, help="fail below this share of model-backed runs answered by the model")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="    log: %(message)s")
    cases = [c for c in load_cases() if not args.case or c["id"] in args.case]
    if not cases:
        print("No matching cases.")
        return 2

    failures = 0
    sources: Counter[str] = Counter()
    latencies: list[float] = []
    runs: list[dict] = []
    print(f"{'case':48} {'source':9} {'ms':>6}  picks / check")
    for case in cases:
        ctx = context_for(case)
        for _ in range(args.repeat):
            started = time.monotonic()
            if args.offline:
                r = deterministic_advice(ctx, case.get("message") or "")
                expect = case["fallback"]
            else:
                r = advise(ctx, AdviceRequest(message=case.get("message")))
                expect = case.get("live", {})
            ms = (time.monotonic() - started) * 1000
            found = problems(case, ctx, r, expect)
            if args.offline:
                found += [f"summary lacks {n!r}" for n in expect.get("summaryContains", []) if n not in r.summary]
            modelled = ctx.open and bool(ctx.offers) and not args.offline
            if modelled:
                sources[r.source] += 1
                latencies.append(ms)
            failures += bool(found)
            picks = ",".join(p.offer_id for p in r.picks) or "-"
            label = "rules" if args.offline else (r.source if modelled else "no model")
            print(f"{case['id']:48} {label:9} {ms:6.0f}  {picks}  {'OK' if not found else 'FAIL: ' + '; '.join(found)}")
            if args.show:
                print(f"    summary: {r.summary}")
                for p in r.picks:
                    print(f"    {p.offer_id}: {p.why}")
            runs.append(
                {"case": case["id"], "source": label, "ms": round(ms), "picks": [p.offer_id for p in r.picks],
                 "summary": r.summary, "problems": found}
            )

    total = sum(sources.values())
    ai_rate = sources["ai"] / total if total else None
    print()
    print(f"cases run: {len(cases)} x {args.repeat}; failed expectations: {failures}")
    if total:
        print(f"model-backed runs: {total}; ai: {sources['ai']} ({100 * sources['ai'] / total:.0f}%); fallback: {sources['fallback']}")
        print(f"latency ms: median {statistics.median(latencies):.0f}, max {max(latencies):.0f}")
    report = {
        "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "offline" if args.offline else "live",
        "model": None if args.offline else get_settings().bedrock_model_id,
        "repeat": args.repeat,
        "failed": failures,
        "aiRate": ai_rate,
        "runs": runs,
    }
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(f"report saved: {args.report}")
    if args.compare:
        compare(report, json.loads(Path(args.compare).read_text()))
    if ai_rate is not None and ai_rate < args.min_ai_rate:
        print(f"ai rate {ai_rate:.0%} is below the required {args.min_ai_rate:.0%}")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

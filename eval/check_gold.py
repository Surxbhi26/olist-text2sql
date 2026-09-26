"""Run every gold query and flag errors or empty results. Run before an eval: python -m eval.check_gold"""
import sys

from agent.executor import execute
from eval.common import load_questions

questions = load_questions()
bad = 0
counts = {}
for q in questions:
    counts[q["difficulty"]] = counts.get(q["difficulty"], 0) + 1
    r = execute(q["gold_sql"])
    if not r["ok"]:
        bad += 1
        print(f"[ERROR] {q['id']}: {r['error']}")
        continue
    if not r["rows"]:
        bad += 1
        print(f"[EMPTY] {q['id']}: {q['question']}")
        continue
    preview = ", ".join(f"{c}={v}" for c, v in zip(r["columns"], r["rows"][0]))
    print(f"[ OK  ] {q['id']:>4} {q['difficulty']:<6} {len(r['rows']):>4} rows  {preview[:70]}")

print(f"\n{len(questions)} questions ({', '.join(f'{n} {d}' for d, n in sorted(counts.items()))}); "
      f"{len(questions) - bad} gold queries OK, {bad} problem(s)")
sys.exit(1 if bad else 0)
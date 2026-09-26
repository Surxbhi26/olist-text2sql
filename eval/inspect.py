"""Show the model's SQL and results next to the gold results.

  python -m eval.inspect N14 N18            strategy D by default
  python -m eval.inspect Q01 --strategy B
  python -m eval.inspect --failed           every failed question for the strategy
"""
import argparse
import json
import re

from agent.llm import model_name
from eval.common import RESULTS_DIR, load_questions

ap = argparse.ArgumentParser()
ap.add_argument("ids", nargs="*")
ap.add_argument("--strategy", default="D")
ap.add_argument("--run", default=re.sub(r"[^A-Za-z0-9_.-]", "_", model_name()))
ap.add_argument("--failed", action="store_true")
args = ap.parse_args()

gold_sql = {q["id"]: q["gold_sql"] for q in load_questions()}
recs = {}
for line in (RESULTS_DIR / f"{args.run}.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line)
        if r["strategy"] == args.strategy.upper():
            recs[r["id"]] = r

ids = [i for i in recs if not recs[i]["final_match"]] if args.failed else args.ids
for i in ids:
    r = recs.get(i)
    if r is None:
        print(f"{i}: no result for strategy {args.strategy}\n")
        continue
    status = "MATCH" if r["final_match"] else ("valid, wrong answer" if r["final_valid"] else "SQL error")
    print("=" * 90)
    print(f"{i} [{r['difficulty']}, {r['category']}] {status}, {r['attempts']} attempt(s)")
    print(f"Q: {r['question']}\n")
    print("MODEL SQL:\n" + r["final_sql"] + "\n")
    if r["final_error"]:
        print(f"ERROR: {r['final_error']}\n")
    print(f"MODEL ROWS ({r['pred_rows']}): {r['pred_preview']}")
    print(f"GOLD  ROWS ({r['gold_rows']}): {r['gold_preview']}\n")
    print("GOLD SQL:\n" + gold_sql.get(i, "?") + "\n")
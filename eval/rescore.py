"""Re-score saved predictions against the CURRENT gold queries, without calling the LLM.
Use after fixing a gold query. Re-executes each stored first/final SQL and recomputes the matches.

  python -m eval.rescore                 default run (model name)
  python -m eval.rescore --run smoke
A backup of the old results is written to <run>.jsonl.bak first."""
import argparse
import json
import re
import shutil

from agent.executor import execute
from agent.llm import model_name
from eval.common import RESULTS_DIR, load_questions, normalize_sql, results_match, to_jsonable

ap = argparse.ArgumentParser()
ap.add_argument("--run", default=re.sub(r"[^A-Za-z0-9_.-]", "_", model_name()))
run = ap.parse_args().run
path = RESULTS_DIR / f"{run}.jsonl"
shutil.copy(path, path.with_suffix(".jsonl.bak"))

questions = {q["id"]: q for q in load_questions()}
gold = {}
for qid, q in questions.items():
    g = execute(q["gold_sql"])
    if not g["ok"]:
        raise SystemExit(f"Gold query {qid} fails: {g['error']}. Run python -m eval.check_gold")
    gold[qid] = g


def rematch(sql, valid, g):
    if not valid:
        return False, []
    r = execute(sql)
    if not r["ok"]:
        return False, []
    return results_match(g["columns"], g["rows"], r["columns"], r["rows"]), r["rows"]


recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
changed = []
for rec in recs:
    g = gold.get(rec["id"])
    if g is None:
        continue
    before = (rec["first_match"], rec["final_match"])
    rec["first_match"], _ = rematch(rec["first_sql"], rec["first_valid"], g)
    rec["final_match"], rows = rematch(rec["final_sql"], rec["final_valid"], g)
    rec["gold_rows"], rec["gold_preview"] = len(g["rows"]), to_jsonable(g["rows"], 5)
    if rec["final_valid"]:
        rec["pred_rows"], rec["pred_preview"] = len(rows), to_jsonable(rows, 5)
    rec["exact_match"] = normalize_sql(rec["first_sql"]) == normalize_sql(questions[rec["id"]]["gold_sql"])
    if before != (rec["first_match"], rec["final_match"]):
        changed.append(f"{rec['strategy']} {rec['id']}: final {before[1]} -> {rec['final_match']}")

path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
print(f"Rescored {len(recs)} results ({len(changed)} changed). Backup: {path.with_suffix('.jsonl.bak')}")
for c in changed:
    print("  " + c)
print(f"\nNow run: python -m eval.score --run {run}")
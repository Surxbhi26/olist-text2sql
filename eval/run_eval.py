"""Run the evaluation. Resumable: results are appended per (question, strategy), and finished
pairs are skipped on rerun.

  python -m eval.run_eval                        all questions, strategies D, B, A
  python -m eval.run_eval --strategies D         only RAG + retry (also yields C)
  python -m eval.run_eval --ids Q01,N06          a subset
  python -m eval.run_eval --limit 3              quick smoke test
  python -m eval.run_eval --run my_run_name      separate results file

Strategy C (RAG, single attempt) is D's first attempt: same prompt at temperature 0,
so it needs no extra LLM calls.
"""
import argparse
import datetime as dt
import json
import os
import re
import time

import psycopg
from dotenv import load_dotenv

from agent.engine import ask, generate_and_run
from agent.executor import execute
from agent.llm import model_name
from eval.common import RESULTS_DIR, load_questions, normalize_sql, results_match, to_jsonable

load_dotenv()

BASELINE_CONTEXT = "### Database\nA PostgreSQL database for Olist, a Brazilian e-commerce marketplace."
_HIDDEN = {"agent_log", "schema_chunks"}
_ddl_cache = None


def schema_ddl():
    """Strategy B context: raw table/column/type list, no descriptions, glossary, or examples."""
    global _ddl_cache
    if _ddl_cache is None:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            rows = conn.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                                   WHERE table_schema = 'public' ORDER BY table_name, ordinal_position""").fetchall()
        tables = {}
        for t, c, d in rows:
            if t not in _HIDDEN:
                tables.setdefault(t, []).append(f"{c} {d}")
        _ddl_cache = "### Database schema (PostgreSQL)\n" + "\n".join(
            f"CREATE TABLE {t} ({', '.join(cols)});" for t, cols in tables.items())
    return _ddl_cache


def _match(attempt, gold):
    if attempt["stage"] not in ("ok", "empty"):
        return False
    return results_match(gold["columns"], gold["rows"], attempt["columns"], attempt["rows"])


def run_one(q, strategy, gold):
    start = time.time()
    if strategy == "D":
        r = ask(q["question"], exclude_examples=q["exclude"], strategy="eval", log=False)
        attempts = r["attempts"]
    else:
        context = BASELINE_CONTEXT if strategy == "A" else schema_ddl()
        a = generate_and_run(q["question"], context, examples=())
        a["n"] = 1
        attempts = [a]

    first, final = attempts[0], attempts[-1]
    return {
        "id": q["id"], "strategy": strategy, "difficulty": q["difficulty"], "category": q["category"],
        "question": q["question"], "model": model_name(),
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "first_valid": first["stage"] in ("ok", "empty"),
        "first_match": _match(first, gold),
        "first_sql": first["sql"],
        "first_error": first["error"],
        "first_llm_s": first["llm_s"],
        "first_input_tokens": first["input_tokens"],
        "final_valid": final["stage"] in ("ok", "empty"),
        "final_match": _match(final, gold),
        "final_sql": final["sql"],
        "final_error": final["error"],
        "attempts": len(attempts),
        "latency_s": round(time.time() - start, 2),
        "input_tokens": sum(a["input_tokens"] for a in attempts),
        "output_tokens": sum(a["output_tokens"] for a in attempts),
        "exact_match": normalize_sql(first["sql"]) == normalize_sql(q["gold_sql"]),
        "pred_rows": len(final["rows"]),
        "gold_rows": len(gold["rows"]),
        "pred_preview": to_jsonable(final["rows"], 5),
        "gold_preview": to_jsonable(gold["rows"], 5),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, help="results file name (default: model name)")
    ap.add_argument("--strategies", default="D,B,A")
    ap.add_argument("--ids", default=None, help="comma-separated question ids")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    run = args.run or re.sub(r"[^A-Za-z0-9_.-]", "_", model_name())
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{run}.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done.add((rec["id"], rec["strategy"]))

    questions = load_questions()
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[:args.limit]
    strategies = [s.strip().upper() for s in args.strategies.split(",")]

    todo = [(s, q) for s in strategies for q in questions if (q["id"], s) not in done]
    print(f"Run '{run}' -> {path}")
    print(f"{len(questions)} questions x {len(strategies)} strategies: "
          f"{len(done)} already done, {len(todo)} to run. Model: {model_name()}\n")

    gold_cache, times = {}, []
    with path.open("a", encoding="utf-8") as out:
        for i, (strategy, q) in enumerate(todo, 1):
            if q["id"] not in gold_cache:
                g = execute(q["gold_sql"])
                if not g["ok"]:
                    print(f"  SKIP {q['id']}: gold query fails ({g['error']}). Run python -m eval.check_gold")
                    gold_cache[q["id"]] = None
                else:
                    gold_cache[q["id"]] = g
            gold = gold_cache[q["id"]]
            if gold is None:
                continue
            try:
                rec = run_one(q, strategy, gold)
            except Exception as e:  # noqa: BLE001 - e.g. Ollama timeout; not saved, so it reruns next time
                print(f"[{i}/{len(todo)}] {strategy} {q['id']}: CRASHED ({e}); will retry on next run")
                continue
            out.write(json.dumps(rec) + "\n")
            out.flush()
            times.append(rec["latency_s"])
            eta_min = (sum(times) / len(times)) * (len(todo) - i) / 60
            mark = "MATCH" if rec["final_match"] else ("valid" if rec["final_valid"] else "error")
            extra = f", {rec['attempts']} attempts" if rec["attempts"] > 1 else ""
            print(f"[{i}/{len(todo)}] {strategy} {q['id']:>4} {mark:<5} {rec['latency_s']:>6.1f}s{extra}"
                  f"   ETA ~{eta_min:.0f} min")

    print(f"\nDone. Score it with: python -m eval.score --run {run}")


if __name__ == "__main__":
    main()
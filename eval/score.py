"""Summarize an eval run: python -m eval.score --run <name>
Writes eval/results/<run>_summary.md and eval/results/<run>_failures.csv."""
import argparse
import csv
import json
import re

from agent.llm import model_name
from eval.common import RESULTS_DIR

NAMES = {"A": "A: Baseline (question only)", "B": "B: Schema only",
         "C": "C: RAG (1 attempt)", "D": "D: RAG + self-correction"}
DIFFS = ["easy", "medium", "hard"]


def load(run):
    recs = [json.loads(l) for l in (RESULTS_DIR / f"{run}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = {}
    for r in recs:  # if a pair was run twice, keep the latest
        latest[(r["id"], r["strategy"])] = r
    return list(latest.values())


def views(recs):
    """Per strategy: list of (record, match, valid, attempts, latency, tokens_in). C comes from D's first attempt."""
    out = {}
    for r in recs:
        s = r["strategy"]
        if s == "D":
            out.setdefault("C", []).append((r, r["first_match"], r["first_valid"], 1,
                                            r["first_llm_s"], r["first_input_tokens"]))
        out.setdefault(s, []).append((r, r["final_match"], r["final_valid"], r["attempts"],
                                      r["latency_s"], r["input_tokens"]))
    return {k: out[k] for k in "ABCD" if k in out}


def pct(xs):
    return f"{100 * sum(xs) / len(xs):.0f}%" if xs else "-"


def avg(xs, fmt="{:.1f}"):
    return fmt.format(sum(xs) / len(xs)) if xs else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=re.sub(r"[^A-Za-z0-9_.-]", "_", model_name()))
    run = ap.parse_args().run
    recs = load(run)
    v = views(recs)
    lines = [f"# Eval results: `{run}`", "",
             f"{len({r['id'] for r in recs})} questions. Execution match = the query's result equals the gold "
             "query's result (column names/order ignored, small rounding tolerance).", "",
             "| Strategy | Execution match | Valid SQL | Exact SQL match | Avg attempts | Avg latency (s) | Avg tokens in |",
             "|---|---|---|---|---|---|---|"]
    for s, rows in v.items():
        exact = [r["exact_match"] for r, *_ in rows]
        lines.append(f"| {NAMES[s]} ({len(rows)}) | **{pct([m for _, m, *_ in rows])}** | "
                     f"{pct([val for _, _, val, *_ in rows])} | {pct(exact)} | "
                     f"{avg([a for *_, a, _, _ in rows])} | {avg([l for *_, l, _ in rows], '{:.0f}')} | "
                     f"{avg([t for *_, t in rows], '{:.0f}')} |")

    lines += ["", "## Execution match by difficulty", "",
              "| Strategy | " + " | ".join(f"{d} (n)" for d in DIFFS) + " |",
              "|---|" + "---|" * len(DIFFS)]
    for s, rows in v.items():
        cells = []
        for d in DIFFS:
            ms = [m for r, m, *_ in rows if r["difficulty"] == d]
            cells.append(f"{pct(ms)} ({len(ms)})")
        lines.append(f"| {NAMES[s]} | " + " | ".join(cells) + " |")

    lines += ["", "## Execution match by category", "", "| Category | " + " | ".join(v) + " |",
              "|---|" + "---|" * len(v)]
    for cat in sorted({r["category"] for r in recs}):
        cells = [pct([m for r, m, *_ in rows if r["category"] == cat]) for rows in v.values()]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")

    if "D" in v:
        d = [r for r, *_ in v["D"]]
        rescued = [r["id"] for r in d if not r["first_match"] and r["final_match"]]
        fixed_errors = [r["id"] for r in d if not r["first_valid"] and r["final_valid"]]
        first_errors = [r["id"] for r in d if not r["first_valid"]]
        lines += ["", "## Self-correction", "",
                  f"- First-attempt SQL errors: {len(first_errors)}; fixed by retry: {len(fixed_errors)} "
                  f"({pct([r['id'] in fixed_errors for r in d if not r['first_valid']])})",
                  f"- Questions turned from wrong to correct by retry: {len(rescued)} {rescued}"]

    if "B" in v and "C" in v:
        b = {r["id"]: m for r, m, *_ in v["B"]}
        c = {r["id"]: m for r, m, *_ in v["C"]}
        helped = sorted(i for i in c if c[i] and not b.get(i, False))
        hurt = sorted(i for i in c if not c[i] and b.get(i, False))
        lines += ["", "## RAG vs schema-only (B vs C)", "",
                  f"- RAG fixed: {len(helped)} {helped}", f"- RAG broke: {len(hurt)} {hurt}"]

    summary = "\n".join(lines) + "\n"
    (RESULTS_DIR / f"{run}_summary.md").write_text(summary, encoding="utf-8")
    print(summary)

    fail_path = RESULTS_DIR / f"{run}_failures.csv"
    with fail_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "id", "difficulty", "category", "question", "error", "pred_rows",
                    "gold_rows", "pred_sql", "failure_type"])
        for s, rows in v.items():
            for r, m, *_ in rows:
                if not m:
                    first = s == "C"
                    w.writerow([s, r["id"], r["difficulty"], r["category"], r["question"],
                                r["first_error"] if first else r["final_error"], r["pred_rows"],
                                r["gold_rows"], r["first_sql"] if first else r["final_sql"], ""])
    print(f"Wrote {RESULTS_DIR / (run + '_summary.md')} and {fail_path}")
    print("Fill in failure_type in the CSV (wrong join / wrong column / misread glossary / "
          "wrong aggregation / wrong filter / other) to build the failure breakdown.")


if __name__ == "__main__":
    main()
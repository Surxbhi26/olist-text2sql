"""Text-to-SQL engine with self-correction.
question -> retrieve context -> LLM -> validate -> execute -> on failure, feed the error back and retry."""
import os
import re
import sys
import time
import uuid

import psycopg
from dotenv import load_dotenv

from agent.executor import execute
from agent.llm import chat, model_name
from agent.prompt import build_prompt, extract_sql, select_examples
from agent.retriever import format_context, retrieve
from agent.session import Session, Turn, looks_like_followup, rewrite
from agent.validator import validate

load_dotenv()
MAX_ATTEMPTS = 3
RETRY_TEMPERATURE = 0.3  # attempt 1 is deterministic; retries get slight randomness to avoid repeating

# Common Postgres errors mapped to concrete fix instructions. Small models often ignore a raw
# error message; an explicit "how to fix" makes the retry far more likely to change the query.
REPAIR_HINTS = [
    (r"must appear in the GROUP BY clause",
     "Every selected column that is not inside an aggregate (SUM, AVG, COUNT, MIN, MAX) must be in "
     "GROUP BY. For a per-group average, wrap the column in AVG(...)."),
    (r"function round\(double precision",
     "ROUND(x, 2) needs numeric. Write ROUND(x::numeric, 2)."),
    (r"missing FROM-clause entry for table",
     "A table alias is used where it is not defined. Aliases inside a subquery or CTE are not visible "
     "outside it; refer to the subquery's own alias or column names."),
    (r"column .* does not exist",
     "Use only the columns listed in the context for that table, and check the table alias prefix."),
    (r"relation .* does not exist", "Use only the tables listed in the context."),
    (r"operator does not exist",
     "The two sides have different types. Add an explicit cast, e.g. ::date, ::timestamp or ::numeric."),
    (r"division by zero", "Wrap the denominator in NULLIF(x, 0)."),
    (r"statement timeout",
     "The query is too slow. Filter earlier, avoid cross joins, or use a PRECOMPUTED summary table."),
    (r"syntax error|parse error", "Fix the SQL syntax. Output exactly one PostgreSQL SELECT statement."),
]
EMPTY_RESULT_MSG = ("Query ran but returned 0 rows. If an empty result is plausible for this question, "
                    "return the same query unchanged. Otherwise fix the filters, joins, or date range.")


def generate_and_run(question, context, examples, previous_attempts=(), temperature=0.0,
                     previous_turn=None):
    """One attempt: prompt the LLM, validate its SQL, execute it."""
    system, user = build_prompt(question, context, examples, previous_attempts, previous_turn)
    llm = chat(system, user, temperature=temperature)
    sql = extract_sql(llm["text"])
    attempt = {"sql": sql, "raw": llm["text"], "llm_s": llm["latency_s"],
               "input_tokens": llm["input_tokens"], "output_tokens": llm["output_tokens"],
               "columns": [], "rows": [], "error": None, "stage": None}

    v = validate(sql)
    if not v.ok:
        attempt.update(error=v.error, stage="validation")
        return attempt

    attempt["sql"] = v.sql
    res = execute(v.sql)
    if not res["ok"]:
        attempt.update(error=res["error"], stage="execution")
        return attempt

    attempt.update(columns=res["columns"], rows=res["rows"], stage="ok")
    return attempt


def _normalize(sql):
    return re.sub(r"\s+", " ", sql or "").strip().lower()


def _feedback(sql, error, failed_sqls):
    """Build retry feedback: the error, a fix hint if we recognize it, and a warning on repeats."""
    msg = error
    for pattern, hint in REPAIR_HINTS:
        if re.search(pattern, error or "", re.I):
            msg += f"\nHow to fix: {hint}"
            break
    if _normalize(sql) in failed_sqls:
        msg += "\nYou already tried this exact query and it failed. Write a DIFFERENT query."
    return {"sql": sql, "error": msg}


def ask(question, max_attempts=MAX_ATTEMPTS, k_examples=3, exclude_examples=(),
        strategy="rag+retry", session=None, log=True):
    """Answer a question, retrying on validation errors, execution errors, and (once) empty results.
    With a Session, follow-ups are rewritten into standalone questions and build on the previous SQL."""
    start = time.time()

    # Phase 6: resolve follow-ups before retrieval, so retrieval sees the full question.
    standalone, rewrite_s, previous_turn = question, 0.0, None
    if session is not None and session.turns and looks_like_followup(question):
        standalone, rewrite_s = rewrite(question, session.turns)
        previous_turn = session.turns[-1]

    retrieved = retrieve(standalone)
    context = format_context(retrieved)
    k = 1 if previous_turn is not None else k_examples
    examples = select_examples(standalone, k=k, exclude=exclude_examples)

    attempts, feedback, failed_sqls = [], [], set()
    for n in range(1, max_attempts + 1):
        temp = 0.0 if n == 1 else RETRY_TEMPERATURE
        a = generate_and_run(standalone, context, examples, feedback, temperature=temp,
                             previous_turn=previous_turn)
        a["n"], a["temperature"] = n, temp
        attempts.append(a)

        if a["stage"] != "ok":
            a["repeated"] = _normalize(a["sql"]) in failed_sqls
            feedback.append(_feedback(a["sql"], a["error"], failed_sqls))
            failed_sqls.add(_normalize(a["sql"]))
            continue

        if a["rows"] or n == max_attempts:
            break
        # Empty result: retry once. If the model repeats the same query, accept the empty answer.
        if len(attempts) >= 2 and _normalize(a["sql"]) == _normalize(attempts[-2]["sql"]):
            break
        a["stage"] = "empty"
        feedback.append({"sql": a["sql"], "error": EMPTY_RESULT_MSG})

    final = attempts[-1]
    if final["stage"] == "empty":
        final["stage"] = "ok"  # accepted empty result

    result = {
        "question": question,
        "standalone": standalone,
        "rewritten": standalone != question,
        "rewrite_s": rewrite_s,
        "tables": [t["name"] for t in retrieved["tables"]],
        "examples": [e["id"] for e in examples],
        "attempts": attempts,
        "final": final,
        "success": final["stage"] == "ok",
        "total_s": round(time.time() - start, 2),
    }
    if session is not None and result["success"]:
        session.add(Turn(question=question, standalone=standalone, sql=final["sql"],
                         columns=final["columns"], row_count=len(final["rows"])))
    if log:
        _log(result, strategy, session.id if session is not None else str(uuid.uuid4()))
    return result


_LOG_DDL = """
CREATE TABLE IF NOT EXISTS agent_log (
    id            SERIAL PRIMARY KEY,
    ts            TIMESTAMPTZ DEFAULT now(),
    session_id    TEXT,
    strategy      TEXT,
    model         TEXT,
    question      TEXT,
    attempt       INT,
    is_final      BOOLEAN,
    stage         TEXT,       -- ok | empty | validation | execution
    sql           TEXT,
    error         TEXT,
    row_count     INT,
    llm_s         REAL,
    input_tokens  INT,
    output_tokens INT
)"""


def _log(result, strategy, session_id):
    """Write every attempt to agent_log. Never lets a logging failure break the answer."""
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
            conn.execute(_LOG_DDL)
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO agent_log (session_id, strategy, model, question, attempt, is_final,
                           stage, sql, error, row_count, llm_s, input_tokens, output_tokens)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(session_id, strategy, model_name(), result["standalone"], a["n"],
                      a is result["final"], a["stage"], a["sql"], a["error"], len(a["rows"]),
                      a["llm_s"], a["input_tokens"], a["output_tokens"])
                     for a in result["attempts"]])
    except Exception as e:  # noqa: BLE001
        print(f"(warning: could not write agent_log: {e})", file=sys.stderr)


def print_result(r):
    print(f"Question: {r['question']}")
    if r.get("rewritten"):
        print(f"Rewritten: {r['standalone']}  ({r['rewrite_s']}s)")
    print(f"Tables:   {', '.join(r['tables'])}")
    print(f"Examples: {', '.join(r['examples']) or 'none'}")

    for a in r["attempts"]:
        status = a["stage"] if not a["error"] else f"{a['stage']} error: {a['error']}"
        extra = " [REPEATED a failed query]" if a.get("repeated") else ""
        print(f"\n--- Attempt {a['n']} ({a['llm_s']}s, temp {a.get('temperature', 0)}): {status}{extra}")
        print(a["sql"])

    f = r["final"]
    print("\n=== Result ===")
    if not r["success"]:
        print(f"FAILED after {len(r['attempts'])} attempts: {f['error']}")
    else:
        import pandas as pd
        df = pd.DataFrame(f["rows"], columns=f["columns"])
        if len(r["attempts"]) == 1:
            note = ""
        elif len(df) == 0:
            note = " (empty result accepted after retry)"
        else:
            note = f" (fixed on attempt {len(r['attempts'])})"
        print(f"{len(df)} rows{note}")
        print(df.head(10).to_string(index=False))
    tin = sum(a["input_tokens"] for a in r["attempts"])
    tout = sum(a["output_tokens"] for a in r["attempts"])
    print(f"\nTotal {r['total_s']}s, {len(r['attempts'])} attempt(s), tokens in/out {tin}/{tout}")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "How many orders are there per order status?"
    print_result(ask(q))
"""Execute validated SQL as the read-only role, with a timeout."""
import os
import time

import psycopg
from dotenv import load_dotenv

load_dotenv()
TIMEOUT_MS = 10_000


def execute(sql, timeout_ms=TIMEOUT_MS):
    """Returns {ok, columns, rows, error, exec_s}. Never raises on SQL errors,
    because the error text is fed back to the LLM in the self-correction loop."""
    start = time.time()
    try:
        with psycopg.connect(os.environ["READONLY_DATABASE_URL"]) as conn:
            conn.read_only = True  # layer 3: read-only transaction, on top of the role's defaults
            conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
            cur = conn.execute(sql)
            columns = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall() if cur.description else []
            conn.rollback()
        return {"ok": True, "columns": columns, "rows": rows, "error": None,
                "exec_s": round(time.time() - start, 3)}
    except psycopg.Error as e:
        diag = getattr(e, "diag", None)
        msg = (diag.message_primary if diag and diag.message_primary else str(e)).strip()
        if diag and diag.message_hint:
            msg += f" HINT: {diag.message_hint}"
        return {"ok": False, "columns": [], "rows": [], "error": msg,
                "exec_s": round(time.time() - start, 3)}

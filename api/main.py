"""FastAPI service for the Olist text-to-SQL engine.

  uvicorn api.main:app --port 8000
  Interactive docs: http://localhost:8000/docs
"""
import datetime as dt
import os
import urllib.request
from decimal import Decimal
from threading import Lock

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent.engine import ask
from agent.llm import OLLAMA_URL, PROVIDER, model_name
from agent.retriever import retrieve
from agent.session import Session

load_dotenv()

app = FastAPI(title="Olist Text-to-SQL", version="1.0",
              description="Ask questions about the Olist e-commerce data in plain English.")

SESSIONS: dict[str, Session] = {}   # in-memory; would be Redis or a DB table in production
_llm_lock = Lock()                  # a CPU-bound local model can't serve requests in parallel


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    session_id: str | None = None


class ResetRequest(BaseModel):
    session_id: str


def _json(v):
    """Make a database value JSON-safe."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def _get_session(session_id):
    if session_id and session_id in SESSIONS:
        return SESSIONS[session_id]
    session = Session(id=session_id) if session_id else Session()
    SESSIONS[session.id] = session
    return session


@app.get("/health")
def health():
    """Check that the database and the LLM are reachable (no LLM generation)."""
    db_ok = llm_ok = False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        pass
    if PROVIDER == "ollama":
        try:
            urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
            llm_ok = True
        except Exception:  # noqa: BLE001
            pass
    else:
        llm_ok = bool(os.getenv("ANTHROPIC_API_KEY"))
    return {"status": "ok" if db_ok and llm_ok else "degraded", "database": db_ok, "llm": llm_ok,
            "provider": PROVIDER, "model": model_name(), "sessions": len(SESSIONS)}


_stats_cache = {}


@app.get("/stats")
def stats():
    """Headline dataset numbers for the UI header (plain SQL, cached, no LLM)."""
    if not _stats_cache:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            row = conn.execute("""
                SELECT (SELECT COUNT(*) FROM orders),
                       (SELECT COUNT(DISTINCT customer_unique_id) FROM customers),
                       (SELECT COUNT(*) FROM sellers),
                       (SELECT SUM(oi.price) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
                        WHERE o.order_status NOT IN ('canceled', 'unavailable')),
                       (SELECT MIN(order_purchase_timestamp)::date FROM orders),
                       (SELECT MAX(order_purchase_timestamp)::date FROM orders)
            """).fetchone()
        _stats_cache.update(orders=row[0], customers=row[1], sellers=row[2], revenue=float(row[3]),
                            first_date=row[4].isoformat(), last_date=row[5].isoformat())
    return _stats_cache


@app.get("/schema")
def schema(q: str):
    """Debug retrieval: which tables and business definitions a question would get."""
    r = retrieve(q)
    return {"question": q,
            "tables": [{"name": t["name"], "distance": t["distance"]} for t in r["tables"]],
            "terms": [{"name": t["name"], "distance": t["distance"]} for t in r["terms"]],
            "context_preview": [t["content"] for t in r["tables"] + r["terms"]]}


@app.post("/ask")
def ask_question(req: AskRequest):
    """Answer a question. Pass the returned session_id back to ask follow-ups."""
    session = _get_session(req.session_id)
    if not _llm_lock.acquire(timeout=900):
        raise HTTPException(503, "The model is busy with another question. Try again shortly.")
    try:
        r = ask(req.question, session=session, strategy="api")
    except RuntimeError as e:  # e.g. Ollama not reachable
        raise HTTPException(502, str(e)) from e
    finally:
        _llm_lock.release()

    final = r["final"]
    return {
        "session_id": session.id,
        "question": r["question"],
        "standalone": r["standalone"],
        "rewritten": r["rewritten"],
        "success": r["success"],
        "sql": final["sql"],
        "columns": final["columns"],
        "rows": [[_json(v) for v in row] for row in final["rows"]],
        "row_count": len(final["rows"]),
        "error": None if r["success"] else final["error"],
        "attempts": [{"n": a["n"], "stage": a["stage"], "sql": a["sql"], "error": a["error"],
                      "llm_s": a["llm_s"], "temperature": a.get("temperature", 0.0)}
                     for a in r["attempts"]],
        "tables": r["tables"],
        "examples": r["examples"],
        "total_s": r["total_s"],
    }


@app.post("/reset")
def reset(req: ResetRequest):
    """Start a new conversation for this session id."""
    SESSIONS.pop(req.session_id, None)
    return {"session_id": req.session_id, "reset": True}

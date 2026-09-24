"""Compare rag/descriptions.yaml with the live Postgres schema and report drift."""
import os
import sys
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

load_dotenv()
DESCRIPTIONS = Path("rag/descriptions.yaml")
IGNORED_TABLES = {"schema_chunks", "agent_log"}  # internal tables, not for the LLM


def live_schema(conn):
    rows = conn.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """).fetchall()
    schema = {}
    for table, column, dtype in rows:
        if table not in IGNORED_TABLES:
            schema.setdefault(table, {})[column] = dtype
    return schema


def check(conn=None):
    """Return a list of problems (empty list means descriptions match the database)."""
    doc = yaml.safe_load(DESCRIPTIONS.read_text(encoding="utf-8"))
    own_conn = conn is None
    conn = conn or psycopg.connect(os.environ["DATABASE_URL"])
    try:
        db = live_schema(conn)
    finally:
        if own_conn:
            conn.close()

    problems = []
    described = {t["name"]: t for t in doc["tables"]}

    for name in sorted(set(db) - set(described)):
        problems.append(f"Table in DB but not described: {name} (columns: {', '.join(db[name])})")

    for name, t in described.items():
        if name not in db:
            problems.append(f"Described table not in DB: {name}")
            continue
        doc_cols, db_cols = set(t["columns"]), set(db[name])
        for c in sorted(doc_cols - db_cols):
            problems.append(f"{name}.{c}: described but not in DB")
        for c in sorted(db_cols - doc_cols):
            problems.append(f"{name}.{c}: in DB ({db[name][c]}) but not described")

    for rel in doc.get("relationships", []):
        for side in (s.strip() for s in rel.split("=")):
            table, _, column = side.partition(".")
            if column not in db.get(table, {}):
                problems.append(f"Relationship uses missing column: {side}  ({rel})")

    return problems


if __name__ == "__main__":
    problems = check()
    if problems:
        print(f"{len(problems)} mismatch(es) between descriptions.yaml and the database:\n")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("descriptions.yaml matches the database: every table and column is described.")
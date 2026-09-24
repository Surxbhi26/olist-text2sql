"""Chunk descriptions + glossary, embed them, and store them in pgvector (schema_chunks)."""
import os
import sys
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

from rag.check_descriptions import check, live_schema
from rag.embed import DIM, embed, to_pgvector

load_dotenv()


def table_chunk(t, types):
    lines = [f"Table: {t['name']}", " ".join(t["description"].split()), "Columns:"]
    for col, desc in t["columns"].items():
        dtype = types.get(col, "unknown")
        note = " [double precision: use ROUND(x::numeric, 2)]" if dtype == "double precision" else ""
        lines.append(f"- {col} ({dtype}){note}: {desc}")
    return "\n".join(lines)


def glossary_chunk(g):
    return "\n".join([
        f"Business term: {g['term']} (also: {', '.join(g.get('aliases', []))})",
        f"Definition: {' '.join(g['definition'].split())}",
        f"SQL hint: {g['sql_hint']}",
    ])


def main():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        problems = check(conn)
        if problems:
            print("Fix descriptions.yaml first (run python -m rag.check_descriptions):")
            for p in problems:
                print("  -", p)
            sys.exit(1)

        db = live_schema(conn)
        desc = yaml.safe_load(Path("rag/descriptions.yaml").read_text(encoding="utf-8"))
        gloss = yaml.safe_load(Path("rag/glossary.yaml").read_text(encoding="utf-8"))

        chunks = [("table", t["name"], table_chunk(t, db[t["name"]])) for t in desc["tables"]]
        chunks += [("glossary", g["term"], glossary_chunk(g)) for g in gloss["terms"]]
        chunks.append(("joins", "relationships",
                       "Join relationships (foreign keys):\n" + "\n".join(desc["relationships"])))

        print(f"Embedding {len(chunks)} chunks (first run downloads the model)...")
        vectors = embed([text for _, _, text in chunks])

        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS schema_chunks")
        conn.execute(f"""
            CREATE TABLE schema_chunks (
                id        SERIAL PRIMARY KEY,
                kind      TEXT NOT NULL,          -- table | glossary | joins
                name      TEXT NOT NULL,
                content   TEXT NOT NULL,
                embedding VECTOR({DIM}) NOT NULL
            )
        """)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO schema_chunks (kind, name, content, embedding) VALUES (%s, %s, %s, %s::vector)",
                [(k, n, c, to_pgvector(v)) for (k, n, c), v in zip(chunks, vectors)],
            )
        conn.execute("CREATE INDEX ON schema_chunks USING hnsw (embedding vector_cosine_ops)")

        counts = conn.execute("SELECT kind, COUNT(*) FROM schema_chunks GROUP BY kind ORDER BY kind").fetchall()
    print("Indexed:", ", ".join(f"{n} {k}" for k, n in counts))


if __name__ == "__main__":
    main()
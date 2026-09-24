"""Retrieve the schema and glossary chunks most relevant to a question."""
import os
import sys

import psycopg
from dotenv import load_dotenv

from rag.embed import embed, to_pgvector

load_dotenv()

_QUERY = """
    SELECT name, content, embedding <=> %s::vector AS distance
    FROM schema_chunks WHERE kind = %s
    ORDER BY distance LIMIT %s
"""

# If a table is retrieved, its companion is added: they're almost always queried together.
COMPANIONS = {
    "products": ["product_categories"],
    "product_categories": ["products"],
    "order_items": ["orders"],
}


def retrieve(question, k_tables=4, k_terms=3):
    """Top tables and glossary terms are retrieved separately so neither crowds out the other.
    Companion tables and the join map are always added, because join paths matter most."""
    vec = to_pgvector(embed([question])[0])
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        tables = conn.execute(_QUERY, (vec, "table", k_tables)).fetchall()
        terms = conn.execute(_QUERY, (vec, "glossary", k_terms)).fetchall()
        joins = conn.execute("SELECT content FROM schema_chunks WHERE kind = 'joins'").fetchone()

        names = {n for n, _, _ in tables}
        extra = sorted({c for t in names for c in COMPANIONS.get(t, []) if c not in names})
        if extra:
            rows = conn.execute(
                "SELECT name, content FROM schema_chunks WHERE kind = 'table' AND name = ANY(%s)",
                (extra,)).fetchall()
            tables += [(n, c, None) for n, c in rows]

    def pack(rows):
        return [{"name": n, "content": c, "distance": None if d is None else round(d, 3)}
                for n, c, d in rows]

    return {"tables": pack(tables), "terms": pack(terms), "joins": joins[0] if joins else ""}


def format_context(r):
    """Turn retrieval results into the text block that goes into the LLM prompt."""
    parts = ["### Relevant tables"] + [t["content"] for t in r["tables"]]
    parts += ["### Business definitions"] + [t["content"] for t in r["terms"]]
    parts += ["### " + r["joins"]]
    return "\n\n".join(parts)


def _show(items):
    return ", ".join(
        f"{t['name']} ({'companion' if t['distance'] is None else t['distance']})" for t in items)


if __name__ == "__main__":
    q = " ".join(a for a in sys.argv[1:] if a != "--full") or "What is the repeat customer rate?"
    r = retrieve(q)
    print(f"Question: {q}\n")
    print("Tables:  ", _show(r["tables"]))
    print("Glossary:", _show(r["terms"]))
    if "--full" in sys.argv:
        print("\n" + format_context(r))
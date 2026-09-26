"""Build the text-to-SQL prompt: rules + retrieved context + few-shot examples + question."""
import re
from functools import lru_cache
from pathlib import Path

from rag.embed import embed

GROUND_TRUTH_DIR = Path("sql/ground_truth")

SYSTEM = """You are an expert PostgreSQL 16 analyst for the Olist Brazilian e-commerce database.
Write ONE read-only SQL query that answers the user's question.

Rules:
1. Output only the SQL query. No explanation, no markdown fences.
2. Exactly one SELECT statement. WITH (CTEs) is allowed. Never write INSERT, UPDATE, DELETE, DROP, CREATE, ALTER or any other statement that changes data.
3. Use ONLY tables and columns listed in the context. Never invent a column or table name.
4. Follow the business definitions in the context exactly (revenue, valid order, repeat customer, etc.).
   Exclude canceled/unavailable orders ONLY for money metrics (revenue, sales, GMV, order value),
   using NOT IN ('canceled', 'unavailable'). Counts of orders, customers, sellers, statuses, reviews,
   and delivery metrics use all orders with no status filter.
5. Tables marked PRECOMPUTED already contain the aggregation. Prefer them when they answer the question.
6. The data ends in 2018. For relative dates ("last 90 days", "recent"), anchor to (SELECT MAX(order_purchase_timestamp) FROM orders), never NOW() or CURRENT_DATE.
7. Use ROUND(x::numeric, 2) for rounding, and NULLIF(denominator, 0) for every division.
8. Qualify columns with short table aliases when joining.
9. Give readable column aliases in the output, and add ORDER BY when the question implies ranking."""


# Matches headers like "-- Q03: question", "-- ### Q01 | easy | question", "-- Q7) question".
_HEADER = re.compile(r"^\s*--\s*#*\s*(Q\d+)\b(.*)$", re.I)
_DIFFICULTIES = {"easy", "medium", "hard"}


def _split_header(rest):
    """'| easy | How many orders...' -> ('easy', 'How many orders...')."""
    parts = [p.strip() for p in re.split(r"\|", rest.strip().lstrip(":.-)").strip()) if p.strip()]
    difficulty = next((p.lower() for p in parts if p.lower() in _DIFFICULTIES), None)
    text = [p for p in parts if p.lower() not in _DIFFICULTIES]
    return difficulty, (text[-1] if text else "")


def _parse_file(path):
    """Split a .sql file into question/SQL examples.
    Supports many queries per file, each starting with a header comment like '-- Q03: question',
    or one query per file where the first comment line is the question."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks, cur = [], None
    for line in lines:
        m = _HEADER.match(line)
        if m:
            if cur:
                blocks.append(cur)
            difficulty, question = _split_header(m.group(2))
            cur = {"id": m.group(1).upper(), "question": question,
                   "difficulty": difficulty, "sql": []}
        elif cur is not None:
            if line.strip().startswith("--"):
                if not cur["question"]:          # header had no text: next comment is the question
                    cur["question"] = line.strip()[2:].strip()
            else:
                cur["sql"].append(line)
    if cur:
        blocks.append(cur)

    if not blocks:  # no Qnn headers: whole file is one example
        comments = [l.strip()[2:].strip() for l in lines if l.strip().startswith("--")]
        body = [l for l in lines if not l.strip().startswith("--")]
        if comments:
            blocks = [{"id": path.stem, "question": comments[0], "difficulty": None, "sql": body}]

    examples = []
    for b in blocks:
        sql = "\n".join(b["sql"]).strip().rstrip(";").strip()
        if b["question"] and sql:
            examples.append({"id": b["id"], "question": b["question"],
                             "difficulty": b["difficulty"], "sql": sql})
    return examples


@lru_cache(maxsize=1)
def load_examples():
    """Load question/SQL pairs from every file in sql/ground_truth/."""
    examples = []
    for path in sorted(GROUND_TRUTH_DIR.glob("*.sql")):
        examples.extend(_parse_file(path))
    vectors = embed([e["question"] for e in examples]) if examples else []
    for e, v in zip(examples, vectors):
        e["vec"] = v
    return examples


def select_examples(question, k=3, exclude=()):
    """Pick the k ground-truth examples most similar to the question.
    `exclude` holds example ids to hold out (used in evaluation to avoid leakage)."""
    pool = [e for e in load_examples() if e["id"] not in set(exclude)]
    if not pool:
        return []
    qv = embed([question])[0]
    pool.sort(key=lambda e: -sum(a * b for a, b in zip(qv, e["vec"])))
    return pool[:k]


def build_prompt(question, context, examples=(), previous_attempts=(), previous_turn=None):
    """Return (system, user) messages.
    previous_attempts: list of {"sql", "error"} for the self-correction loop (Phase 5).
    previous_turn: the last conversation turn, when the question is a follow-up (Phase 6)."""
    parts = [context]
    if examples:
        parts.append("### Examples")
        for e in examples:
            parts.append(f"Question: {e['question']}\nSQL:\n{e['sql']}")
    if previous_turn is not None:
        parts.append("### Previous question in this conversation. The new question is a follow-up: "
                     "modify this SQL to answer it instead of starting from scratch.")
        parts.append(f"Question: {previous_turn.standalone}\nSQL:\n{previous_turn.sql}")
    if previous_attempts:
        parts.append("### Previous attempts that failed. Fix the problem; do not repeat the mistake.")
        for i, a in enumerate(previous_attempts, 1):
            parts.append(f"Attempt {i} SQL:\n{a['sql']}\nError: {a['error']}")
    parts.append(f"### Question\n{question}\n\nSQL:")
    return SYSTEM, "\n\n".join(parts)


def extract_sql(text):
    """Pull the SQL out of a model response (handles fences, reasoning tags, and preamble)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1)
    start = re.search(r"\b(WITH|SELECT)\b", text, flags=re.I)
    if start:
        text = text[start.start():]
    return text.strip().rstrip(";").strip()


if __name__ == "__main__":
    ex = load_examples()
    print(f"Loaded {len(ex)} examples from {GROUND_TRUTH_DIR}/")
    for e in ex:
        print(f"  {e['id']:>4}  {(e['difficulty'] or '-'):<6}  {e['question'][:65]}"
              f"  ({len(e['sql'].splitlines())} lines)")

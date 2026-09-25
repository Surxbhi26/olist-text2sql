"""Validate LLM-generated SQL before execution. Layer 1 of defense in depth
(layer 2 is the read-only role; layer 3 is statement_timeout)."""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

MAX_ROWS = 1000

# Backstop keyword list, checked after string literals and comments are removed.
BLOCKED = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE",
    "COPY", "MERGE", "CALL", "DO", "EXECUTE", "PREPARE", "VACUUM", "ANALYZE", "REFRESH",
    "LOCK", "LISTEN", "NOTIFY", "REINDEX", "CLUSTER", "COMMENT", "SECURITY",
    # dangerous functions
    "PG_SLEEP", "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "LO_IMPORT", "LO_EXPORT",
    "DBLINK", "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND", "SET_CONFIG",
]
_BLOCKED_RE = re.compile(r"\b(" + "|".join(BLOCKED) + r")\b", re.I)

_SET_OPS = (exp.SetOperation,) if hasattr(exp, "SetOperation") else (exp.Union, exp.Intersect, exp.Except)
_ALLOWED_ROOTS = (exp.Select,) + _SET_OPS
_FORBIDDEN_NODES = tuple(getattr(exp, n) for n in
                         ["Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Merge", "Into"]
                         if hasattr(exp, n))


@dataclass
class Validation:
    ok: bool
    sql: str
    error: str | None = None


def strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql).strip()


def _without_literals(sql):
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)   # 'string literals'
    return re.sub(r'"[^"]*"', '""', sql)          # "quoted identifiers"


def validate(sql):
    sql = strip_comments(sql).rstrip(";").strip()
    if not sql:
        return Validation(False, sql, "Empty query.")

    # 1. Parse: exactly one statement, and it must be a SELECT (optionally WITH ... SELECT, or UNION).
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        return Validation(False, sql, f"SQL parse error: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return Validation(False, sql, f"Expected exactly 1 statement, got {len(statements)}.")
    tree = statements[0]
    if not isinstance(tree, _ALLOWED_ROOTS):
        return Validation(False, sql, f"Only SELECT queries are allowed, got {type(tree).__name__}.")

    # 2. No write/DDL nodes anywhere, including inside CTEs. SELECT ... INTO creates a table.
    bad = tree.find(*_FORBIDDEN_NODES)
    if bad is not None:
        return Validation(False, sql, f"Forbidden operation in query: {type(bad).__name__}.")
    if tree.args.get("locks"):
        return Validation(False, sql, "Row locking (FOR UPDATE / FOR SHARE) is not allowed.")

    # 3. Keyword backstop, in case the parser misses something.
    hit = _BLOCKED_RE.search(_without_literals(sql))
    if hit:
        return Validation(False, sql, f"Blocked keyword: {hit.group(1).upper()}.")

    # 4. Cap result size. Appending text (instead of regenerating SQL) keeps the query unchanged.
    if tree.args.get("limit") is None and tree.args.get("fetch") is None:
        sql = f"{sql}\nLIMIT {MAX_ROWS}"

    return Validation(True, sql)

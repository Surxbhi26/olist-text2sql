"""Shared eval helpers: load the question set, normalize values, and compare result sets."""
import datetime as dt
import math
import re
from decimal import Decimal
from pathlib import Path

import yaml

from agent.prompt import load_examples

QUESTIONS_FILE = Path("eval/questions.yaml")
RESULTS_DIR = Path("eval/results")


# ---------------------------------------------------------------- questions
def load_questions():
    doc = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    ground_truth = {e["id"]: e for e in load_examples()}
    questions = []
    for item in doc["questions"]:
        if "ref" in item:
            ref = item["ref"]
            if ref not in ground_truth:
                raise KeyError(f"questions.yaml references {ref}, which is not in sql/ground_truth/")
            e = ground_truth[ref]
            questions.append({
                "id": ref,
                "question": item.get("question", e["question"]),
                "gold_sql": e["sql"],
                "difficulty": item.get("difficulty") or e.get("difficulty") or "hard",
                "category": item.get("category", "ground_truth"),
                "exclude": [ref] + item.get("exclude", []),
            })
        else:
            questions.append({
                "id": item["id"],
                "question": item["question"],
                "gold_sql": item["gold_sql"].strip().rstrip(";"),
                "difficulty": item["difficulty"],
                "category": item.get("category", "new"),
                "exclude": item.get("exclude", []),
            })
    ids = [q["id"] for q in questions]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate question ids: {sorted(dupes)}")
    return questions


# ---------------------------------------------------------------- values
class Num(float):
    """A float that remembers how many decimal places it came with (dp=None: an integer value)."""
    def __new__(cls, value, dp):
        obj = super().__new__(cls, value)
        obj.dp = dp
        return obj


def _decimals(v):
    """Decimal places a value was given with. None for integers, capped at 6 for unrounded floats."""
    if isinstance(v, (bool, int)):
        return None
    if isinstance(v, Decimal):
        exp = v.as_tuple().exponent
        return (-exp if exp < 0 else None) if isinstance(exp, int) else None
    s = repr(float(v))
    if "e" in s or "E" in s:
        return 6
    dp = len(s.split(".")[1]) if "." in s else 0
    return min(dp, 6) if dp else None


def norm(v):
    """Normalize a cell so equivalent values compare equal across queries."""
    if v is None:
        return None
    if isinstance(v, (bool, int, float, Decimal)):
        return Num(float(v), _decimals(v))
    if isinstance(v, (dt.datetime, dt.date)):
        s = v.isoformat()
        return re.sub(r"[T ]00:00:00(\+00:00)?$", "", s)  # timestamp at midnight == date
    return str(v).strip()


def to_jsonable(rows, limit=20):
    """First `limit` rows as JSON-safe lists (for storing a preview in results)."""
    out = []
    for r in rows[:limit]:
        out.append([x if isinstance(x, (str, int, float)) or x is None else norm(x) for x in r])
    return out


def _close(a, b):
    """Numbers match if they agree at the COARSER of their two precisions:
    -8.03 vs -8.0 match (compared at 1 decimal); 0.45 vs 0.48 do not (both 2 decimals).
    Integers must match exactly."""
    if isinstance(a, float) and isinstance(b, float):
        dps = [d for d in (getattr(a, "dp", None), getattr(b, "dp", None)) if d is not None]
        if not dps:
            return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        half_unit = 0.5 * 10 ** -min(dps)
        return abs(a - b) <= half_unit + 1e-9 or math.isclose(a, b, rel_tol=1e-6)
    return a == b


def _key(v):
    if v is None:
        return (0, 0.0, "")
    if isinstance(v, float):
        return (1, round(v, 2), "")
    return (2, 0.0, str(v))


def _same_column(a, b):
    return len(a) == len(b) and all(_close(x, y) for x, y in zip(sorted(a, key=_key), sorted(b, key=_key)))


# ---------------------------------------------------------------- comparison
def results_match(gold_cols, gold_rows, pred_cols, pred_rows):
    """Execution match: same number of rows, and every gold column has a matching predicted column
    (by values, ignoring names and column order). Extra predicted columns are allowed.
    Rows are then compared as a multiset, with small numeric tolerance for rounding."""
    if len(gold_rows) != len(pred_rows):
        return False
    if not gold_rows:
        return True
    g = [[norm(v) for v in r] for r in gold_rows]
    p = [[norm(v) for v in r] for r in pred_rows]
    g_cols = list(zip(*g))
    p_cols = list(zip(*p))

    mapping, used = [], set()
    for gc in g_cols:
        j = next((j for j, pc in enumerate(p_cols) if j not in used and _same_column(gc, pc)), None)
        if j is None:
            return False
        mapping.append(j)
        used.add(j)

    g_rows = sorted((tuple(r) for r in g), key=lambda r: [_key(x) for x in r])
    p_rows = sorted((tuple(r[j] for j in mapping) for r in p), key=lambda r: [_key(x) for x in r])
    return all(all(_close(a, b) for a, b in zip(gr, pr)) for gr, pr in zip(g_rows, p_rows))


def normalize_sql(sql):
    sql = re.sub(r"\s+", " ", sql or "").strip().rstrip(";").lower()
    return re.sub(r"\s+limit 1000$", "", sql)
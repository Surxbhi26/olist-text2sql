"""Multi-turn context: session history, follow-up detection, and query rewriting."""
import re
import time
import uuid
from dataclasses import dataclass, field

from agent.llm import chat

MAX_TURNS = 5

_FOLLOWUP_RE = re.compile(
    r"\b(that|this|it|its|those|these|them|same|instead|also|again|previous|"
    r"what about|how about|break (it |that |this )?down|split|drill|only|just|"
    r"excluding|except|without|sort|reverse|more|fewer|rather)\b", re.I)
_FOLLOWUP_START_RE = re.compile(r"^\s*(and|but|now|then|by|per|for|in|what about|how about)\b", re.I)

REWRITE_SYSTEM = """You rewrite follow-up questions about an e-commerce database into standalone questions.
Use the conversation to resolve references such as "that", "it", "those", "by state", "only for SP".
Keep every metric, filter, and grouping from the previous question unless the follow-up changes it.
If the new question is already standalone, return it unchanged.
Output only the rewritten question on one line. No explanation."""


@dataclass
class Turn:
    question: str        # what the user typed
    standalone: str      # rewritten, self-contained version
    sql: str
    columns: list
    row_count: int


@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turns: list = field(default_factory=list)

    def add(self, turn):
        self.turns.append(turn)
        del self.turns[:-MAX_TURNS]  # keep only the last MAX_TURNS

    def reset(self):
        self.turns.clear()


def looks_like_followup(question):
    """Cheap check so standalone questions skip the rewrite LLM call."""
    q = question.strip()
    return (len(q.split()) <= 5
            or bool(_FOLLOWUP_START_RE.search(q))
            or bool(_FOLLOWUP_RE.search(q)))


def _clean(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()
    line = next((l for l in text.splitlines() if l.strip()), "")
    line = re.sub(r"^(standalone question|rewritten question|question)\s*:\s*", "", line.strip(), flags=re.I)
    return line.strip().strip('"').strip("'").strip()


def rewrite(question, turns):
    """Rewrite a follow-up into a standalone question using recent turns.
    Returns (standalone_question, seconds). Falls back to the original on failure."""
    history = "\n".join(f"Q{i}: {t.standalone}\n   (answered with columns: {', '.join(t.columns)})"
                        for i, t in enumerate(turns[-3:], 1))
    user = f"Conversation so far:\n{history}\n\nFollow-up: {question}\n\nStandalone question:"
    start = time.time()
    try:
        out = _clean(chat(REWRITE_SYSTEM, user)["text"])
    except Exception:  # noqa: BLE001 - never block the answer on the rewrite step
        out = ""
    return (out or question), round(time.time() - start, 2)
"""Multi-turn text-to-SQL in the terminal.

  python -m agent.chat           interactive; type :reset, :history or :quit
  python -m agent.chat --demo    scripted 3-turn conversation
"""
import sys

from agent.engine import ask, print_result
from agent.session import Session, looks_like_followup

DEMO = [
    "Top 10 product categories by revenue",
    "now break that down by customer state",
    "only for SP",
]


def run_turn(session, question):
    print("\n" + "=" * 70)
    tag = "follow-up" if session.turns and looks_like_followup(question) else "new question"
    print(f"[turn {len(session.turns) + 1}, {tag}]")
    print_result(ask(question, session=session, strategy="rag+retry+multiturn"))


def show_history(session):
    if not session.turns:
        print("(no history)")
    for i, t in enumerate(session.turns, 1):
        print(f"{i}. {t.question}")
        if t.standalone != t.question:
            print(f"   -> {t.standalone}")
        print(f"   {t.row_count} rows, columns: {', '.join(t.columns)}")


def main():
    session = Session()
    if "--demo" in sys.argv:
        for q in DEMO:
            run_turn(session, q)
        return

    print("Ask about the Olist data. Commands: :reset  :history  :quit")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            continue
        if q in (":quit", ":q", "exit"):
            break
        if q == ":reset":
            session.reset()
            print("(history cleared)")
            continue
        if q == ":history":
            show_history(session)
            continue
        run_turn(session, q)


if __name__ == "__main__":
    main()
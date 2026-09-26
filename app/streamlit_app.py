"""Streamlit UI for the Olist text-to-SQL API.

  streamlit run app/streamlit_app.py
Requires the API: uvicorn api.main:app --port 8000
"""
import html
import numbers
import os
from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
RESULTS_DIR = Path("eval/results")
EXAMPLES = [
    ("📦", "Top 10 product categories by revenue"),
    ("🔁", "What percentage of customers are repeat customers?"),
    ("🚚", "Average delivery delay by customer state"),
    ("⏰", "What share of delivered orders arrived late?"),
    ("💳", "What percentage of total payment value was paid by credit card?"),
    ("❌", "How many orders were canceled?"),
]

st.set_page_config(page_title="Olist Text-to-SQL", page_icon="🛒", layout="wide")
st.session_state.setdefault("messages", [])
st.session_state.setdefault("session_id", None)

# ---------------------------------------------------------------- styling
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1200px;}
.hero {padding: 1.4rem 1.6rem; border-radius: 16px; margin-bottom: 1rem;
       background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #db2777 100%); color: #fff;}
.hero h1 {margin: 0; font-size: 1.9rem; color: #fff;}
.hero p {margin: .35rem 0 0; opacity: .92; font-size: 1rem;}
.kpis {display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .7rem; margin: .2rem 0 1.1rem;}
.kpi {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: .7rem .9rem;}
.kpi .label {font-size: .78rem; opacity: .7; text-transform: uppercase; letter-spacing: .04em;}
.kpi .value {font-size: 1.35rem; font-weight: 700; margin-top: .1rem;}
.chips {display: flex; flex-wrap: wrap; gap: .4rem; margin: .1rem 0 .6rem;}
.chip {font-size: .8rem; padding: .18rem .6rem; border-radius: 999px; border: 1px solid rgba(128,128,128,.3);}
.chip.ok {background: rgba(16,185,129,.12); border-color: rgba(16,185,129,.45);}
.chip.warn {background: rgba(245,158,11,.14); border-color: rgba(245,158,11,.5);}
.chip.bad {background: rgba(239,68,68,.12); border-color: rgba(239,68,68,.45);}
.interp {font-size: .88rem; opacity: .8; margin-bottom: .3rem;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- API helpers
def api_get(path, timeout=5):
    try:
        r = requests.get(f"{API}{path}", timeout=timeout)
        return r.json() if r.ok else None
    except requests.RequestException:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def get_stats():
    return api_get("/stats", timeout=15)


health = api_get("/health")
stats = get_stats() if health else None


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### 🛒 Olist Text-to-SQL")
    if health is None:
        st.error("API not reachable.\n\nStart it with:\n`uvicorn api.main:app --port 8000`")
    elif health["status"] == "ok":
        st.success(f"Connected · `{health['model']}`")
    else:
        st.warning(f"Degraded · database {'ok' if health['database'] else 'DOWN'} · "
                   f"LLM {'ok' if health['llm'] else 'DOWN'}")
    if st.button("🔄 New conversation"):
        if st.session_state.session_id:
            try:
                requests.post(f"{API}/reset", json={"session_id": st.session_state.session_id}, timeout=5)
            except requests.RequestException:
                pass
        st.session_state.messages, st.session_state.session_id = [], None
        st.rerun()
    st.divider()
    st.markdown("**Follow-ups work.** After a question, try:")
    st.markdown("- *now break that down by state*\n- *only for SP*\n- *and by month?*")
    st.divider()
    st.caption("Local model on CPU: answers take about 1–2 minutes. "
               "Queries run on a read-only database role.")


# ---------------------------------------------------------------- header
st.markdown("""
<div class="hero">
  <h1>Ask the Olist data anything</h1>
  <p>Plain English in, PostgreSQL out: grounded by schema retrieval, checked by a SQL safety layer,
  and self-correcting when a query fails.</p>
</div>""", unsafe_allow_html=True)

if stats:
    def kpi(label, value):
        return f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div></div>'
    st.markdown('<div class="kpis">'
                + kpi("Orders", f"{stats['orders']:,}")
                + kpi("Customers", f"{stats['customers']:,}")
                + kpi("Sellers", f"{stats['sellers']:,}")
                + kpi("Revenue", f"R$ {stats['revenue'] / 1e6:.1f}M")
                + kpi("Period", f"{stats['first_date'][:7]} → {stats['last_date'][:7]}")
                + "</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- answer rendering
def pipeline_chips(a):
    chips = [("ok", f"🔎 {len(a['tables'])} tables retrieved")]
    if a.get("rewritten"):
        chips.append(("ok", "💬 follow-up rewritten"))
    n = len(a["attempts"])
    if a["success"]:
        chips.append(("ok", "🛡️ SQL validated"))
        chips.append(("ok", f"⚡ {a['row_count']} rows"))
        if n > 1:
            chips.append(("warn", f"🔁 fixed on attempt {n}"))
    else:
        chips.append(("bad", f"✖ failed after {n} attempts"))
    chips.append(("", f"⏱ {a['total_s']:.0f}s"))
    return '<div class="chips">' + "".join(
        f'<span class="chip {cls}">{html.escape(text)}</span>' for cls, text in chips) + "</div>"


def auto_chart(df):
    """Pick a sensible chart: line for dates, sorted bars for categories. None if not chartable."""
    if df.empty or len(df) > 200:
        return None
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cats = [c for c in df.columns if c not in nums]
    if not nums or not cats:
        return None
    x, y = cats[0], nums[-1]
    color = cats[1] if len(cats) > 1 and df[cats[1]].nunique() <= 10 else None
    is_date = df[x].astype(str).str.match(r"^\d{4}-\d{2}").all()
    if is_date:
        enc = dict(x=alt.X(f"{x}:T", title=x), y=alt.Y(f"{y}:Q", title=y), tooltip=list(df.columns))
        if color:
            enc["color"] = alt.Color(f"{color}:N")
        chart = alt.Chart(df).mark_line(point=True).encode(**enc)
    else:
        data = df.sort_values(y, ascending=False).head(25)
        enc = dict(y=alt.Y(f"{x}:N", sort="-x", title=None), x=alt.X(f"{y}:Q", title=y),
                   tooltip=list(df.columns))
        if color:
            enc["color"] = alt.Color(f"{color}:N")
        chart = alt.Chart(data).mark_bar(cornerRadiusEnd=4).encode(**enc)
    return chart.properties(width="container", height=min(420, 60 + 22 * min(len(df), 25)))


def _fmt(v):
    """1234567.5 -> '1,234,567.5'; 625 -> '625'; text unchanged."""
    if isinstance(v, numbers.Integral):
        return f"{int(v):,}"
    if isinstance(v, numbers.Real):
        return f"{float(v):,.2f}".rstrip("0").rstrip(".")
    return str(v)


def render_answer(a, idx):
    if a.get("rewritten"):
        st.markdown(f'<div class="interp">💬 Interpreted as: <i>{html.escape(a["standalone"])}</i></div>',
                    unsafe_allow_html=True)
    st.markdown(pipeline_chips(a), unsafe_allow_html=True)

    if not a["success"]:
        st.error(a["error"])
    df = pd.DataFrame(a["rows"], columns=a["columns"]) if a["success"] else pd.DataFrame()

    # Single-row numeric answers read best as big numbers.
    if a["success"] and len(df) == 1:
        numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if numeric and len(df.columns) <= 4:
            cols = st.columns(len(df.columns))
            for col, name in zip(cols, df.columns):
                col.metric(name.replace("_", " ").capitalize(), _fmt(df[name].iloc[0]))

    chart = auto_chart(df) if a["success"] else None
    tabs = ["📋 Result"] + (["📈 Chart"] if chart is not None else []) + ["🧾 SQL", "🔁 Trace", "🔎 Context"]
    t = dict(zip(tabs, st.tabs(tabs)))

    with t["📋 Result"]:
        if a["success"]:
            st.dataframe(df, hide_index=True)
            st.download_button("⬇ Download CSV", df.to_csv(index=False), file_name="result.csv",
                               mime="text/csv", key=f"dl_{idx}")
        else:
            st.info("No result. See the Trace tab for every attempt.")
    if chart is not None:
        with t["📈 Chart"]:
            st.altair_chart(chart)
    with t["🧾 SQL"]:
        st.code(a["sql"], language="sql")
    with t["🔁 Trace"]:
        for at in a["attempts"]:
            icon = {"ok": "✅", "empty": "⚪", "validation": "🛡️", "execution": "❌"}.get(at["stage"], "•")
            st.markdown(f"**{icon} Attempt {at['n']}**: {at['stage']} · {at['llm_s']}s · "
                        f"temperature {at['temperature']}")
            st.code(at["sql"], language="sql")
            if at["error"]:
                st.caption(f"Error fed back to the model: {at['error']}")
    with t["🔎 Context"]:
        st.markdown("**Tables retrieved:** " + ", ".join(f"`{x}`" for x in a["tables"]))
        st.markdown("**Few-shot examples:** " + (", ".join(f"`{x}`" for x in a["examples"]) or "none"))
        if a.get("rewritten"):
            st.markdown(f"**Standalone question:** {a['standalone']}")


# ---------------------------------------------------------------- tabs
tab_ask, tab_eval, tab_how = st.tabs(["💬 Ask", "📊 Evaluation", "⚙️ How it works"])

with tab_ask:
    if not st.session_state.messages:
        st.markdown("##### Try one of these")
        cols = st.columns(3)
        for i, (icon, q) in enumerate(EXAMPLES):
            if cols[i % 3].button(f"{icon}  {q}", key=f"ex_{i}"):
                st.session_state.pending = q

    for i, m in enumerate(st.session_state.messages):
        with st.chat_message(m["role"]):
            if m["role"] == "user":
                st.markdown(m["content"])
            else:
                render_answer(m["answer"], i)

    question = st.chat_input("Ask about orders, revenue, customers, sellers…") \
        or st.session_state.pop("pending", None)
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Retrieving schema → writing SQL → validating → running…"):
                try:
                    resp = requests.post(f"{API}/ask", timeout=900,
                                         json={"question": question,
                                               "session_id": st.session_state.session_id})
                except requests.RequestException as e:
                    resp, err = None, str(e)
            if resp is None:
                st.error(f"Request failed: {err}")
            elif resp.ok:
                answer = resp.json()
                st.session_state.session_id = answer["session_id"]
                render_answer(answer, len(st.session_state.messages))
                st.session_state.messages.append({"role": "assistant", "answer": answer})
            else:
                try:
                    detail = resp.json().get("detail", resp.text)
                except ValueError:
                    detail = resp.text
                st.error(f"API error {resp.status_code}: {detail}")

with tab_eval:
    summaries = sorted(p for p in RESULTS_DIR.glob("*_summary.md") if not p.name.startswith("smoke"))
    if not summaries:
        st.info("No evaluation results yet. Run `python -m eval.run_eval` then `python -m eval.score`.")
    else:
        names = [p.name.removesuffix("_summary.md") for p in summaries]
        choice = st.selectbox("Evaluation run", names, index=len(names) - 1)
        st.markdown((RESULTS_DIR / f"{choice}_summary.md").read_text(encoding="utf-8"))
    analysis = Path("eval/failure_analysis.md")
    if analysis.exists():
        with st.expander("Failure analysis (hand-labeled)"):
            st.markdown(analysis.read_text(encoding="utf-8"))

with tab_how:
    st.markdown("#### Pipeline")
    st.graphviz_chart("""
    digraph {
      rankdir=LR; bgcolor="transparent";
      node [shape=box, style="rounded,filled", fillcolor="#eef2ff", color="#6366f1", fontname="Helvetica", fontsize=11];
      edge [color="#94a3b8", fontname="Helvetica", fontsize=9];
      Q [label="Question"]; RW [label="Follow-up\\nrewrite"]; R [label="Retrieve schema +\\nglossary (pgvector)"];
      P [label="Prompt:\\nrules + context +\\nfew-shot + history"]; L [label="LLM\\n(Ollama / Claude)"];
      V [label="Validator\\n(sqlglot)"]; X [label="Execute\\n(read-only role)"]; A [label="Answer", fillcolor="#dcfce7", color="#16a34a"];
      Q -> RW -> R -> P -> L -> V -> X -> A;
      V -> L [label="rejected", style=dashed, color="#f59e0b"];
      X -> L [label="error + repair hint", style=dashed, color="#ef4444"];
    }""")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Safety: three layers")
        st.markdown(
            "1. **Validator**: parses with sqlglot, allows exactly one SELECT, blocks writes inside CTEs, "
            "`SELECT INTO`, `pg_sleep`, file access, row locks; adds `LIMIT 1000`.\n"
            "2. **Read-only role**: the database itself refuses writes, even if the validator were bypassed.\n"
            "3. **Timeout**: `statement_timeout = 10s` stops runaway queries.")
    with c2:
        st.markdown("#### Grounding")
        st.markdown(
            "- Hand-written descriptions of every table and column, plus a business glossary.\n"
            "- Retrieved per question with pgvector; companion tables added for common join paths.\n"
            "- Business rules gated to questions that use the term (an eval finding).\n"
            "- Spark-precomputed summary tables for retention, funnel, and seller trends.")

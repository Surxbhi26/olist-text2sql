# Olist Text-to-SQL: a grounded, self-correcting analytics assistant

Ask business questions about ~100k real Brazilian e-commerce orders in plain English, and get
back PostgreSQL, a result table, and a chart. An LLM writes the SQL, grounded by retrieved
schema descriptions and a business glossary; a three-layer safety system makes sure it can
only read; failed queries are fed back to the model with repair hints; and follow-up questions
build on the previous query.

The part I care most about is the **evaluation**: a 40-question benchmark comparing four
prompting strategies, with every failure inspected by hand.

![Answer view](docs/screenshots/answer.png)

## Key results (qwen2.5-coder:3b, local, CPU)

| Strategy | Execution match | Valid SQL | Avg latency |
|---|---|---|---|
| A: Question only | 2% | 18% | 29s |
| B: Raw schema | 25% | 58% | 27s |
| C: RAG (descriptions + glossary + few-shot) | 32% | 88% | 98s |
| D: RAG + self-correction | 32% | 90% | 110s |
| **D v2: + gated business rules, consistent ground truth** | **38%** | 85% | ~140s* |

\* v2 ran while the API was also running on the same CPU, so its latency is not comparable.

- **Grounding is essential:** from 2% to 32–38% accuracy, and from 18% to ~90% valid SQL.
- **RAG is a tradeoff for a small model:** it fixed 8 business-term questions (GMV, late rate,
  order value) but broke 5 easy ones, because retrieved business rules were applied where they
  didn't belong. Schema-only scored 75% on easy questions; RAG scored 42%.
- **Self-correction fixes syntax, not logic:** it repaired some SQL errors but turned 0 wrong
  answers into right ones. 44% of failures are valid SQL with the wrong logic, which no
  execution error can reveal.
- **A targeted fix worked where predicted:** gating business rules and standardizing
  definitions fixed exactly the two "incomplete filter" failures it targeted (GMV and revenue by
  year), raising accuracy to 38%.
- **Auditing failures found three bugs in my own benchmark** (see [Evaluation](#evaluation)).

## Architecture

```mermaid
flowchart LR
    Q[Question] --> RW[Follow-up rewrite]
    RW --> R[Retrieve schema + glossary<br/>pgvector]
    R --> P[Prompt: rules + context<br/>+ few-shot + history]
    P --> L[LLM<br/>Ollama / Claude]
    L --> V[Validator<br/>sqlglot]
    V --> X[Execute<br/>read-only role]
    X --> A[Answer]
    V -. rejected .-> L
    X -. error + repair hint .-> L
    subgraph Data platform
      PG[(PostgreSQL)] --> SP[PySpark jobs] --> SUM[(Summary tables)]
    end
    X --- PG
```

| Layer | Tools |
|---|---|
| Storage | PostgreSQL 16 + pgvector (Docker) |
| Batch processing | PySpark 4 (local mode) |
| Retrieval | sentence-transformers `all-MiniLM-L6-v2`, pgvector HNSW index |
| LLM | Ollama `qwen2.5-coder:3b` (switchable to Claude via one `.env` setting) |
| SQL safety | sqlglot validator, read-only Postgres role, statement timeout |
| API / UI | FastAPI, Streamlit, Altair |
| Evaluation | Python harness, execution-match scoring, 40-question YAML benchmark |

## Quick start

Requirements: Python 3.11+, Java 17, Docker Desktop, Ollama.

```powershell
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull qwen2.5-coder:3b

docker run -d --name olist-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=olist `
  -p 5433:5432 -v olist_pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
```

`.env`:

```
DATABASE_URL=postgresql://postgres:pw@127.0.0.1:5433/olist
READONLY_DATABASE_URL=postgresql://olist_readonly:readonly_pw@127.0.0.1:5433/olist
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:3b
NUM_CTX=6144
JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot
HF_HUB_OFFLINE=1
```

Build everything once, then start the app:

```powershell
python etl\load_postgres.py                                          # schema + data
python -m spark.run_all                                              # summary tables + checks
Get-Content sql\readonly_role.sql | docker exec -i olist-pg psql -U postgres -d olist
python -m rag.index_schema                                           # embed descriptions
powershell -ExecutionPolicy Bypass -File .\start.ps1                 # API + UI
```

The UI opens at http://localhost:8501 and the API docs at http://localhost:8000/docs.
From the terminal: `python -m agent.engine "Top 10 categories by revenue"` or `python -m agent.chat`.

## Data layer

The 9 Olist CSVs are loaded into a normalized schema with primary and foreign keys, CHECK
constraints, and indexes on join and filter columns. Data issues found and handled:

- `customer_id` is per order; `customer_unique_id` is the real person. All customer, repeat, and
  retention analysis uses `customer_unique_id`.
- `order_reviews.review_id` is not unique, so the table uses a surrogate key.
- `geolocation` has many rows per zip prefix, so it is aggregated to one row per prefix to avoid join fan-out.
- Source column typos (`product_name_lenght`) are fixed in the schema.
- Some categories have no English translation (handled with `LEFT JOIN` + `COALESCE`).
- The last ~6 weeks of data (Sept–Oct 2018) contain almost only canceled orders, so "recent"
  must be anchored per table: the last seller week is 2018-09-03, but the last order is 2018-10-17.

21 hand-written ground-truth queries (`sql/ground_truth/`) cover easy, medium, and hard questions.

## Spark layer

Three summary tables are precomputed with PySpark and written back to Postgres
(`python -m spark.run_all`):

| Table | Rows | Contents |
|---|---|---|
| `summary_cohort_retention` | 220 | Monthly cohorts by `customer_unique_id` |
| `summary_order_funnel` | 25 | Purchased → approved → shipped → delivered → reviewed, with median stage durations |
| `summary_seller_rolling` | 35,893 | Weekly seller revenue and review score, with 4-calendar-week rolling averages |

`spark/verify.py` reconciles every table against independent SQL: order counts (99,441),
distinct buyers (94,990), and item revenue match exactly.

Design decisions: `rangeBetween` on a week index instead of `rowsBetween`, so weeks without
sales don't stretch the window; medians for stage durations, because some source durations are
negative; `try_divide` for rates, because Spark 4's ANSI mode errors on the zero-order edge
months. Spark is overkill for 100k rows; the point is the precompute-then-serve pattern, and the
same code runs on a cluster by changing `master`.

**Insight:** weighted by cohort size, only **0.48%** of customers order again the month after
their first purchase. A naive `AVG(retention_pct)` reports 5.20%, about 10x too high, because
tiny 2016 cohorts get equal weight. This became a hard benchmark question.

## Grounding (RAG)

- `rag/descriptions.yaml`: a hand-written description of every table and column (12 tables,
  77 columns), including the data gotchas above. `rag/check_descriptions.py` fails if the
  descriptions drift from the live schema.
- `rag/glossary.yaml`: 20 business definitions (revenue, GMV, repeat customer, late delivery,
  retention…), each with a SQL hint.
- Each chunk is embedded and stored in pgvector. Per question, the retriever returns the top 4
  tables and top 3 glossary terms, adds **companion tables** for common join paths
  (`products` ↔ `product_categories`, `order_items` → `orders`), and always includes the join map.
- **Gated business rules** (an eval finding): rules the small model over-applies, like the
  "valid order" status filter or the 90-day "recent" window, are only retrieved when the question
  uses that term.
- Column types are read live from Postgres, and `double precision` columns are tagged with
  "use `ROUND(x::numeric, 2)`", which prevents a common Postgres error.

## Text-to-SQL engine and safety

The prompt combines system rules, retrieved context, three few-shot examples chosen by
similarity from the ground-truth set, and (for follow-ups) the previous query.

Generated SQL passes three independent safety layers:

1. **Validator** (`agent/validator.py`): parses with sqlglot and allows exactly one `SELECT`
   (CTEs and `UNION` allowed). It blocks writes hidden in CTEs, `SELECT ... INTO` (which
   creates a table), `FOR UPDATE`, `pg_sleep`, server-file functions, and a keyword backstop.
   It appends `LIMIT 1000`. 19/19 safety tests pass (`python -m agent.test_validator`).
2. **Read-only role**: queries run as `olist_readonly`, with `default_transaction_read_only = on`.
   With the validator bypassed, `DELETE FROM orders` fails with
   *"cannot execute DELETE in a read-only transaction"*.
3. **Timeout**: `statement_timeout = 10s`.

## Self-correction

Up to 3 attempts. On a validation or execution error, the model gets the failed SQL, the exact
Postgres error, and an **error-specific repair hint** (for example, for "must appear in the
GROUP BY clause": wrap the column in an aggregate). Two further lessons are built in:

- At temperature 0, the 3b model repeated the identical failing query three times. Retries now
  run at temperature 0.3, and repeated queries are flagged back to the model.
- Empty results get one retry. If the model returns the same query again, the empty answer is
  accepted, since "customers with 50 orders" can legitimately be empty.

Every attempt is logged to an `agent_log` table.

## Multi-turn context

Follow-ups are detected cheaply (words like "that", "only", "now", or very short questions) and
rewritten into standalone questions before retrieval, so retrieval sees the full intent:

> "Top 10 categories by revenue" → "now break that down by customer state" →
> *"Top 10 product categories by revenue, broken down by customer state"*

The previous SQL is passed to the model to modify. **Finding:** with 3 few-shot examples, the
model copied a similar example instead of extending its own query, and the error propagated to
the next turn. Using a single example on follow-ups made the previous query the main template,
which fixed it.

## Evaluation

`eval/questions.yaml` has 40 questions: the 21 ground-truth queries plus 19 new ones targeting
glossary terms, traps, and summary tables (12 easy, 19 medium, 9 hard). Each question's own
ground-truth example is **held out** of the few-shot pool, so the model never sees its answer.

**Metric: execution match.** Both the generated and the gold SQL are executed and their results
compared, ignoring column names and order, with numbers compared at the coarser of the two
precisions. Exact SQL string match is reported too, at 0–2%, which shows why it's a poor metric.

```powershell
python -m eval.check_gold        # every gold query runs and returns rows
python -m eval.run_eval          # resumable; ~2 hours on CPU
python -m eval.score             # tables + failures CSV
python -m eval.inspect --failed  # model SQL and rows next to gold, per failure
python -m eval.rescore           # re-grade stored SQL after a gold fix (no LLM calls)
```

### By difficulty

| Strategy | Easy (12) | Medium (19) | Hard (9) |
|---|---|---|---|
| A: Question only | 8% | 0% | 0% |
| B: Raw schema | **75%** | 5% | 0% |
| C / D: RAG (+ retry) | 42% | 42% | 0% |
| D v2: gated rules | 50% | **47%** | 0% |

### Failure breakdown (all 27 D failures inspected by hand)

| Theme | Share | Examples |
|---|---|---|
| Reasoning and query structure | 44% | wrong aggregation grain, per-customer rows instead of a count, grouping by cohort instead of month |
| Business-rule side effects | 30% | "valid order" filter added to "orders per status"; a 90-day window copied into "which month had the most orders" |
| Schema errors retry couldn't fix | 15% | selecting `customer_unique_id` from `orders` without the join, three times |
| Benchmark ambiguity | 11% | payment share by value (glossary) vs by count (gold) |

Full labels: [`eval/failure_analysis.md`](eval/failure_analysis.md).

### Bugs found in my own benchmark

Inspecting failures instead of trusting the number found three problems:

1. **Rounding tolerance too strict:** `-8.0` vs `-8.03` was scored wrong. Fixed by comparing at
   the coarser precision (while `0.45` vs `0.48` still differs).
2. **Relative tolerance too loose:** 0.1% on a R$15.7M GMV hid a R$2,140 error. Tolerance now
   follows each value's stated precision, not its magnitude.
3. **Two revenue definitions:** five gold queries used `<> 'canceled'`, the rest excluded
   canceled and unavailable. The few-shot examples were teaching the model the definition the
   glossary contradicted. Standardized, then rescored without any LLM calls.

### The v2 experiment

Hypothesis from the failure analysis: business rules leak into questions that don't need them.
Changes: gate money rules (valid order, revenue, GMV, AOV) to money questions, gate date-window
rules to questions about recent periods, and make one status-filter rule consistent across the
glossary and the gold answers. Result: **32% → 38%**, with the two targeted failures fixed.
With 40 questions and a non-deterministic local model, the specific fixed cases are stronger
evidence than the 6-point change. The easy-question regressions remain, pointing at the
few-shot examples as the next thing to test.

## API and UI

FastAPI (`api/main.py`, docs at `/docs`):

| Endpoint | Purpose |
|---|---|
| `POST /ask` | `{question, session_id}` → SQL, rows, attempts trace, rewrite |
| `POST /reset` | clear a conversation |
| `GET /schema?q=` | what retrieval returns for a question (debugging) |
| `GET /stats` | headline dataset numbers |
| `GET /health` | database and LLM reachability |

Sessions are kept in memory, and a lock serializes LLM calls, since a CPU-bound local model
can't serve requests in parallel.

The Streamlit UI (`app/streamlit_app.py`) shows live dataset KPIs, example questions, and per
answer: pipeline status chips, the result (big metric cards for single numbers), an automatic
chart, the SQL, the self-correction trace, and the retrieved context. It also displays the
evaluation results and a pipeline diagram.

| | |
|---|---|
| ![Chart](docs/screenshots/chart.png) | ![Follow-up](docs/screenshots/followup.png) |
| ![Evaluation tab](docs/screenshots/evaluation.png) | ![How it works](docs/screenshots/how_it_works.png) |

## What I'd do in production

- **A larger model:** a 3b model hits a ceiling on hard questions (0%). The engine switches to
  Claude with one setting, and a model comparison is a single eval run.
- **Semantic checks:** retry can't catch valid-but-wrong SQL. Result sanity checks (row counts,
  value ranges, comparison with summary tables) or an LLM verification step would target the 44%
  reasoning failures.
- **Question routing:** simple lookups do better with less context, so route by complexity.
- **Containers and orchestration:** Docker Compose for the API, UI, and database; Airflow for the Spark jobs.
- **Persistent sessions and caching** (Redis), per-user rate limits, and query cost limits
  (`EXPLAIN` before execution).
- **Human review and feedback:** thumbs up/down on answers, feeding a growing eval set.
- **PII:** Olist is anonymized; real customer data would need column-level access control.

## Project structure

```
agent/    engine, prompt, retriever, validator, executor, LLM client, sessions, chat CLI
api/      FastAPI service
app/      Streamlit UI
eval/     benchmark, runner, scorer, inspector, rescorer, results, failure analysis
etl/      loading and setup checks
rag/      descriptions, glossary, embedding, indexing, drift check
spark/    summary-table jobs, reconciliation checks
sql/      ground-truth queries, read-only role
start.ps1 one-command startup
```
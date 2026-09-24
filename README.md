# Olist Text-to-SQL Analytics Platform

Ask business questions in plain English and get answers from a real e-commerce database.
An LLM generates PostgreSQL queries, grounded in hand-written schema descriptions and a
business glossary (RAG), with a read-only safety layer, a self-correction loop, and a
measured evaluation of different prompting strategies.

Built on the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce):
~100k real anonymized orders across 9 related tables (2016–2018).

## Architecture

```
Olist CSVs ──> Postgres (normalized schema)
                  │
                  ├──> PySpark ──> summary tables (cohorts, funnel, seller rolling)
                  │
Question ──> retrieve schema + glossary chunks (pgvector)
         ──> LLM generates SQL ──> validator (SELECT-only) ──> read-only execution
         ──> on error: feed error back, retry (max 3) ──> results
```

## Tech stack

| Layer | Tool |
|---|---|
| Storage | PostgreSQL 16 + pgvector (Docker) |
| Batch processing | PySpark 4 (local mode) |
| Schema grounding | sentence-transformers + pgvector |
| SQL validation | sqlglot |
| API / UI | FastAPI, Streamlit |
| Evaluation | Python + CSV test set |

## Project structure

```
data/raw/          Kaggle CSVs (gitignored)
sql/               schema, indexes, ground_truth/ queries
etl/               load_postgres.py, explore.py, check_setup.py
spark/             cohort.py, funnel.py, seller_rolling.py, verify.py, run_all.py
rag/               descriptions.yaml, glossary.yaml, index_schema.py
agent/             retriever, prompt, validator, engine
api/               FastAPI app
app/               Streamlit app
eval/              questions.csv, run_eval.py, known_failures.md, results/
```

## Setup

Requirements: Python 3.11+, Java 17 (for PySpark), Docker Desktop.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

docker run -d --name olist-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=olist `
  -p 5432:5432 -v olist_pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
```

Create `.env` in the project root:

```
DATABASE_URL=postgresql://postgres:pw@localhost:5432/olist
JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot
ANTHROPIC_API_KEY=your_key_here
```

Download the Olist CSVs from Kaggle into `data/raw/`, then:

```powershell
python etl\load_postgres.py          # build and load the database
python -m spark.run_all              # build summary tables + reconciliation checks
```

## Data layer

The raw CSVs are loaded into a normalized schema with primary keys, foreign keys,
CHECK constraints, and indexes on join and filter columns.

**Data-quality issues found and handled**

- `customer_id` is per order; `customer_unique_id` is the real person. All repeat-customer
  and retention analysis uses `customer_unique_id`.
- `order_reviews` has duplicate `review_id`s, so it uses a surrogate key.
- `geolocation` has many rows per zip prefix and no key. It is aggregated to one row per
  prefix to prevent join fan-out.
- Source column typos (`product_name_lenght`, `product_description_lenght`) are fixed in the schema.
- Some product categories have no English translation.
- Some orders have no items, and some are `canceled` or `unavailable`.
- A few orders have a carrier date earlier than the approval date.

**Ground truth:** 21 hand-written SQL queries in `sql/ground_truth/`, covering easy,
medium, and hard business questions. All run successfully and seed the evaluation set.

## Spark layer

Three summary tables are precomputed with PySpark and written back to Postgres.
Rebuild them with `python -m spark.run_all`.

| Table | Rows | Contents |
|---|---|---|
| `summary_cohort_retention` | 220 | Monthly cohorts by `customer_unique_id` (excludes canceled/unavailable) |
| `summary_order_funnel` | 25 | Purchased → approved → shipped → delivered → reviewed, per month, with median stage durations |
| `summary_seller_rolling` | 35,893 | Weekly seller revenue and review score, with 4-calendar-week rolling averages |

**Correctness:** `spark/verify.py` reconciles every table against independent SQL on the
raw tables. Order counts (99,441), distinct buyers (94,990), and total item revenue
(R$13,496,408.43) all match exactly.

**Design decisions**

- The rolling window uses `rangeBetween` on a week index, not `rowsBetween`, so weeks with
  no sales don't silently stretch the window beyond 4 calendar weeks.
- Stage durations use medians, because the source data contains some negative durations.
- Rates use `try_divide`. Edge months (2016, late 2018) have zero orders at some stages,
  and Spark 4's ANSI mode errors on divide-by-zero. NULL is more honest than 0%.
- Spark is overkill for 100k rows. The point is to demonstrate the pattern of precomputing
  expensive aggregations and serving cheap reads. The same code runs on a cluster by
  changing `master`.

**Insight:** Olist is overwhelmingly a one-time-buyer marketplace. Weighted by cohort
size, only **0.48%** of customers order again in the month after their first purchase,
and about 0.2–0.3% in each later month.

**Pitfall found:** a plain `AVG(retention_pct)` reported **5.20%** for month 1, about 10x
too high. Tiny 2016 cohorts (a handful of customers) carried equal weight, and cohorts
with zero returning customers had no row at all. The correct metric weights by cohort
size and counts missing rows as 0. This became a hard eval question (Q21) and a
glossary rule.

## Schema and glossary grounding (RAG)

_TODO (Phase 3)._

## Text-to-SQL engine and safety

_TODO (Phase 4)._

## Self-correction loop

_TODO (Phase 5)._

## Multi-turn context

_TODO (Phase 6)._

## Evaluation

_TODO (Phase 7): results table comparing baseline, schema-only, RAG, and RAG + self-correction._

## API and UI

_TODO (Phase 8)._

## What I'd do in production

_TODO (Phase 9)._
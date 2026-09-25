#1
Q09 first draft error:
column "o.order_purchase_timestamp" must appear in the GROUP BY clause or be used in an aggregate function
Cause: window function PARTITION BY re-computes DATE_TRUNC(...) instead of using the grouped alias.
Fix: aggregate in a CTE first, then apply the window function over the CTE's columns.

#2
Spark funnel: DIVIDE_BY_ZERO on delivered/shipped for edge months (2016, late 2018) with 0 orders at a stage.
Spark 4 ANSI mode raises instead of returning NULL. Fix: F.try_divide.
Postgres equivalent: x / NULLIF(y, 0).

#3
Postgres: ROUND(double precision, int) does not exist.
Spark writes DoubleType as double precision. Fix: ROUND(x::numeric, 2).

#4
Cohort retention: averaging percentages
Wrong: AVG(retention_pct) gave month-1 retention of 5.20%.
Right: weighted by cohort size, with missing rows counted as 0, gives 0.48%.
Cause: tiny 2016 cohorts (a few customers) count equally with 7,000-customer cohorts,
and cohorts with zero returners have no row, so they were silently skipped.
Fix: SUM(active_customers) / SUM(cohort_size) over all cohorts old enough.

#5
Retrieval: "Top 10 categories by revenue" missed product_categories and the category glossary term.
Fix: companion-table expansion (products <-> product_categories, order_items -> orders) + richer aliases.

#6
- "orders per status" (3b model): adds WHERE order_status NOT IN ('canceled','unavailable')
  even though the matching gold example Q01 (no filter) was in the prompt and the glossary hint
  was made conditional. Retrieved business rules override few-shot examples for a small model.
  Measure frequency in Phase 7 (does it also happen without RAG context?).

#7
- "avg weekly revenue per seller, last 4 weeks" (after glossary fix): now averages per seller,
  but used a 90-day window (copied from the "Active customer" hint) and still anchored to
  MAX(order_purchase_timestamp). Small model copies SQL snippets from the wrong glossary term.
  Gold:
  WITH last AS (SELECT MAX(week_start) AS w FROM summary_seller_rolling)
  SELECT seller_id, ROUND(AVG(weekly_revenue)::numeric, 2) AS avg_weekly_revenue
  FROM summary_seller_rolling
  WHERE week_start > (SELECT w FROM last) - INTERVAL '4 weeks'
  GROUP BY seller_id ORDER BY avg_weekly_revenue DESC;  
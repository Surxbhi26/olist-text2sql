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
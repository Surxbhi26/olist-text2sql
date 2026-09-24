-- Q21: What is the overall customer retention rate for months 0-6 after first purchase?
-- Difficulty: hard. Trap: AVG(retention_pct) is wrong (5.20% at month 1); must weight by cohort size.
WITH c AS (SELECT DISTINCT cohort_month, cohort_size FROM summary_cohort_retention),
     m AS (SELECT generate_series(0, 6) AS k)
SELECT m.k AS months_since_first,
       ROUND(100.0 * COALESCE(SUM(r.active_customers), 0) / SUM(c.cohort_size), 2) AS weighted_retention
FROM c CROSS JOIN m
LEFT JOIN summary_cohort_retention r
       ON r.cohort_month = c.cohort_month AND r.months_since_first = m.k
WHERE c.cohort_month + (m.k || ' months')::interval <= (SELECT MAX(cohort_month) FROM c)
GROUP BY m.k ORDER BY m.k;
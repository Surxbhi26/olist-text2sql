import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

# (name, query on summary table, independent SQL on raw tables, tolerance)
CHECKS = [
    ("Funnel: total purchased = all orders",
     "SELECT SUM(purchased) FROM summary_order_funnel",
     "SELECT COUNT(*) FROM orders", 0),

    ("Funnel: approved never exceeds purchased",
     "SELECT COUNT(*) FROM summary_order_funnel WHERE approved > purchased",
     "SELECT 0", 0),

    ("Cohort: sum of cohort sizes = distinct buyers",
     """SELECT SUM(cohort_size) FROM
          (SELECT DISTINCT cohort_month, cohort_size FROM summary_cohort_retention) t""",
     """SELECT COUNT(DISTINCT c.customer_unique_id)
        FROM orders o JOIN customers c USING (customer_id)
        WHERE o.order_status NOT IN ('canceled', 'unavailable')""", 0),

    ("Cohort: month 0 is always 100%",
     "SELECT COUNT(*) FROM summary_cohort_retention WHERE months_since_first = 0 AND retention_pct <> 100",
     "SELECT 0", 0),

    ("Cohort: no negative month offsets",
     "SELECT COUNT(*) FROM summary_cohort_retention WHERE months_since_first < 0",
     "SELECT 0", 0),

    ("Seller: total weekly revenue = item revenue on non-canceled orders",
     "SELECT SUM(weekly_revenue) FROM summary_seller_rolling",
     """SELECT SUM(oi.price) FROM order_items oi
        JOIN orders o USING (order_id) WHERE o.order_status <> 'canceled'""", 1.0),

    ("Seller: review scores within 1-5",
     "SELECT COUNT(*) FROM summary_seller_rolling WHERE avg_review_score NOT BETWEEN 1 AND 5",
     "SELECT 0", 0),
]

failed = 0
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    for name, q_summary, q_raw, tol in CHECKS:
        a = float(conn.execute(q_summary).fetchone()[0] or 0)
        b = float(conn.execute(q_raw).fetchone()[0] or 0)
        ok = abs(a - b) <= tol
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: summary={a:,.2f} raw={b:,.2f}")

print(f"\n{len(CHECKS) - failed}/{len(CHECKS)} checks passed")
sys.exit(1 if failed else 0)
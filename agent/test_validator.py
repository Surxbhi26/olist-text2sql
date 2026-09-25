"""Safety tests for the SQL validator. Run: python -m agent.test_validator"""
from agent.validator import validate

CASES = [
    # (description, sql, should_pass)
    ("simple select", "SELECT order_status, COUNT(*) FROM orders GROUP BY 1", True),
    ("CTE", "WITH x AS (SELECT 1 AS a) SELECT a FROM x", True),
    ("union", "SELECT 1 UNION ALL SELECT 2", True),
    ("keyword inside string literal", "SELECT 'please delete me' AS note", True),
    ("existing limit kept", "SELECT * FROM orders LIMIT 5", True),
    ("trailing comment does not swallow LIMIT", "SELECT * FROM orders -- all orders", True),
    ("drop table", "DROP TABLE orders", False),
    ("delete", "DELETE FROM orders", False),
    ("update", "UPDATE orders SET order_status = 'x'", False),
    ("two statements", "SELECT 1; DROP TABLE orders", False),
    ("select into creates a table", "SELECT * INTO stolen FROM orders", False),
    ("write inside CTE", "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", False),
    ("pg_sleep denial of service", "SELECT pg_sleep(60)", False),
    ("read server files", "SELECT pg_read_file('/etc/passwd')", False),
    ("row locking", "SELECT * FROM orders FOR UPDATE", False),
    ("copy to file", "COPY orders TO '/tmp/x.csv'", False),
    ("grant", "GRANT ALL ON orders TO public", False),
    ("empty", "   ", False),
]

failed = 0
for desc, sql, should_pass in CASES:
    v = validate(sql)
    ok = v.ok == should_pass
    failed += not ok
    verdict = "allowed" if v.ok else f"blocked ({v.error})"
    print(f"[{'PASS' if ok else 'FAIL'}] {desc}: {verdict}")

v = validate("SELECT * FROM orders")
limit_ok = v.sql.rstrip().endswith("LIMIT 1000")
failed += not limit_ok
print(f"[{'PASS' if limit_ok else 'FAIL'}] LIMIT 1000 auto-appended")

total = len(CASES) + 1
print(f"\n{total - failed}/{total} validator tests passed")

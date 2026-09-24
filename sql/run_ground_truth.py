import os, re, time
import psycopg
from dotenv import load_dotenv

load_dotenv()
text = open("sql/ground_truth/queries.sql", encoding="utf-8").read()
blocks = re.split(r"^-- ### ", text, flags=re.M)[1:]

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute("SET statement_timeout = '30s'")
    for b in blocks:
        header, _, sql = b.partition("\n")
        qid, diff, question = [x.strip() for x in header.split("|", 2)]
        print(f"\n[{qid}] ({diff}) {question}")
        try:
            t0 = time.time()
            cur = conn.execute(sql)
            rows = cur.fetchall()
            print(f"  OK: {len(rows)} rows in {time.time() - t0:.2f}s")
            for r in rows[:3]:
                print("   ", r)
        except Exception as e:
            print(f"  ERROR: {e}")
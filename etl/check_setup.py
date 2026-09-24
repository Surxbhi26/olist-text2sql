import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    print(conn.execute("SELECT version()").fetchone()[0])
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    print([r[0] for r in conn.execute("SELECT extname FROM pg_extension").fetchall()])
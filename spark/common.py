import os, sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv
from pyspark.sql import SparkSession

load_dotenv()
os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

_u = urlparse(os.environ["DATABASE_URL"])
JDBC_URL = f"jdbc:postgresql://{_u.hostname}:{_u.port}{_u.path}"
PROPS = {"user": _u.username, "password": _u.password, "driver": "org.postgresql.Driver"}
_JAR = Path("spark/jars/postgresql-42.7.3.jar").resolve()


def get_spark(name):
    return (
        SparkSession.builder.master("local[*]").appName(name)
        .config("spark.driver.extraClassPath", str(_JAR))
        .config("spark.driver.memory", "2g")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )


def read(spark, table):
    return spark.read.jdbc(JDBC_URL, table, properties=PROPS)


def write(df, table, pk_cols):
    """Overwrite the table, then add a primary key and print the row count."""
    df.write.jdbc(JDBC_URL, table, mode="overwrite", properties=PROPS)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({', '.join(pk_cols)})")
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  wrote {table}: {n} rows")
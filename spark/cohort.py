from pyspark.sql import functions as F
from spark.common import get_spark, read, write

spark = get_spark("cohort_retention")

orders = (read(spark, "orders")
          .filter(~F.col("order_status").isin("canceled", "unavailable")))
customers = read(spark, "customers").select("customer_id", "customer_unique_id")

# one row per person per month in which they ordered
activity = (orders.join(customers, "customer_id")
            .select("customer_unique_id",
                    F.date_trunc("month", "order_purchase_timestamp").cast("date").alias("order_month"))
            .distinct())

first = (activity.groupBy("customer_unique_id")
         .agg(F.min("order_month").alias("cohort_month")))
cohort_size = first.groupBy("cohort_month").agg(F.count("*").alias("cohort_size"))

result = (activity.join(first, "customer_unique_id")
          .withColumn("months_since_first",
                      F.months_between("order_month", "cohort_month").cast("int"))
          .groupBy("cohort_month", "months_since_first")
          .agg(F.countDistinct("customer_unique_id").alias("active_customers"))
          .join(cohort_size, "cohort_month")
          .withColumn("retention_pct",
                      F.round(100.0 * F.col("active_customers") / F.col("cohort_size"), 2))
          .orderBy("cohort_month", "months_since_first"))

write(result, "summary_cohort_retention", ["cohort_month", "months_since_first"])
spark.stop()
from pyspark.sql import functions as F
from spark.common import get_spark, read, write

spark = get_spark("order_funnel")

orders = read(spark, "orders")
reviewed = (read(spark, "order_reviews").select("order_id").distinct()
            .withColumn("has_review", F.lit(1)))

def days(a, b):
    return (F.unix_timestamp(b) - F.unix_timestamp(a)) / 86400.0

df = (orders.join(reviewed, "order_id", "left")
      .withColumn("purchase_month",
                  F.date_trunc("month", "order_purchase_timestamp").cast("date")))

agg = df.groupBy("purchase_month").agg(
    F.count("*").alias("purchased"),
    F.count("order_approved_at").alias("approved"),
    F.count("order_delivered_carrier_date").alias("shipped"),
    F.count("order_delivered_customer_date").alias("delivered"),
    F.count("has_review").alias("reviewed"),
    F.percentile_approx(days(F.col("order_purchase_timestamp"), F.col("order_approved_at")), 0.5)
        .alias("median_days_purchase_to_approval"),
    F.percentile_approx(days(F.col("order_approved_at"), F.col("order_delivered_carrier_date")), 0.5)
        .alias("median_days_approval_to_carrier"),
    F.percentile_approx(days(F.col("order_delivered_carrier_date"), F.col("order_delivered_customer_date")), 0.5)
        .alias("median_days_carrier_to_delivery"),
)

def pct(num, den):
    # try_divide returns NULL when den = 0 (Spark 4 ANSI mode errors on plain /)
    return F.round(F.try_divide(100.0 * F.col(num), F.col(den)), 2)

result = (agg
          .withColumn("approved_pct", pct("approved", "purchased"))
          .withColumn("shipped_pct", pct("shipped", "approved"))
          .withColumn("delivered_pct", pct("delivered", "shipped"))
          .withColumn("reviewed_pct", pct("reviewed", "delivered"))
          .withColumn("median_days_purchase_to_approval", F.round("median_days_purchase_to_approval", 2))
          .withColumn("median_days_approval_to_carrier", F.round("median_days_approval_to_carrier", 2))
          .withColumn("median_days_carrier_to_delivery", F.round("median_days_carrier_to_delivery", 2))
          .orderBy("purchase_month"))

write(result, "summary_order_funnel", ["purchase_month"])
spark.stop()
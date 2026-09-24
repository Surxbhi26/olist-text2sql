from pyspark.sql import functions as F, Window
from spark.common import get_spark, read, write

spark = get_spark("seller_rolling")

orders = (read(spark, "orders")
          .filter(F.col("order_status") != "canceled")
          .select("order_id",
                  F.date_trunc("week", "order_purchase_timestamp").cast("date").alias("week_start")))
items = read(spark, "order_items").select("order_id", "seller_id", "price")
order_score = (read(spark, "order_reviews").groupBy("order_id")
               .agg(F.avg("review_score").alias("order_score")))

# one row per (seller, order): revenue and that order's score
seller_orders = (items.join(orders, "order_id")
                 .groupBy("seller_id", "order_id", "week_start")
                 .agg(F.sum("price").alias("order_revenue"))
                 .join(order_score, "order_id", "left"))

weekly = (seller_orders.groupBy("seller_id", "week_start").agg(
    F.round(F.sum("order_revenue"), 2).alias("weekly_revenue"),
    F.count("*").alias("weekly_orders"),
    F.sum("order_score").alias("score_sum"),
    F.count("order_score").alias("scored_orders"),
).withColumn("week_idx", F.floor(F.datediff("week_start", F.lit("2000-01-03").cast("date")) / 7).cast("int")))

w = Window.partitionBy("seller_id").orderBy("week_idx").rangeBetween(-3, 0)

result = (weekly
          .withColumn("rolling_4w_revenue_avg", F.round(F.sum("weekly_revenue").over(w) / 4.0, 2))
          .withColumn("rolling_4w_orders", F.sum("weekly_orders").over(w))
          .withColumn("avg_review_score",
                      F.round(F.try_divide(F.col("score_sum"), F.col("scored_orders")), 2))
          .withColumn("rolling_4w_avg_review_score",
                      F.round(F.try_divide(F.sum("score_sum").over(w),
                                           F.sum("scored_orders").over(w)), 2))
          .drop("score_sum", "scored_orders", "week_idx")
          .orderBy("seller_id", "week_start"))

write(result, "summary_seller_rolling", ["seller_id", "week_start"])
spark.stop()
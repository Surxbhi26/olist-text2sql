from spark.common import get_spark, read

spark = get_spark("smoke")
print("orders:", read(spark, "orders").count())
spark.stop()
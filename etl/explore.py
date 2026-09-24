import glob, os
import pandas as pd

KEYS = {
    "olist_customers_dataset": ["customer_id"],
    "olist_geolocation_dataset": ["geolocation_zip_code_prefix"],
    "olist_orders_dataset": ["order_id"],
    "olist_order_items_dataset": ["order_id", "order_item_id"],
    "olist_order_payments_dataset": ["order_id", "payment_sequential"],
    "olist_order_reviews_dataset": ["review_id"],
    "olist_products_dataset": ["product_id"],
    "olist_sellers_dataset": ["seller_id"],
    "product_category_name_translation": ["product_category_name"],
}

for path in sorted(glob.glob("data/raw/*.csv")):
    name = os.path.basename(path)[:-4]
    df = pd.read_csv(path)
    print(f"\n=== {name}: {df.shape[0]} rows x {df.shape[1]} cols")
    nulls = df.isna().sum()
    print("columns with nulls:", nulls[nulls > 0].to_dict() or "none")
    keys = KEYS.get(name)
    if keys:
        print(f"duplicate rows on key {keys}:", df.duplicated(subset=keys).sum())
    print("full-row duplicates:", df.duplicated().sum())
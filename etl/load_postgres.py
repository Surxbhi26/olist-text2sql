import io, os
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()
RAW = "data/raw"

# Categories used by products but missing from Olist's translation file
EXTRA_CATEGORIES = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_preparers",
}


def read(name, **kw):
    return pd.read_csv(f"{RAW}/{name}.csv", **kw)


def copy_df(conn, table, df):
    cols = ", ".join(df.columns)
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)  # NaN/NaT/<NA> -> empty -> NULL
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)") as cp:
            cp.write(buf.getvalue())
    print(f"  loaded {table:<20} {len(df):>8} rows")


def drop_orphans(df, col, valid_ids, label):
    bad = ~df[col].isin(valid_ids)
    if bad.any():
        print(f"  WARNING: dropping {bad.sum()} {label} rows with unknown {col}")
    return df[~bad]


def main():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        print("Creating schema...")
        conn.execute(open("sql/schema.sql", encoding="utf-8").read())

        print("Loading parents...")
        # product categories (+ the 2 missing translations)
        cats = read("product_category_name_translation")
        products = read("olist_products_dataset").rename(columns={
            "product_name_lenght": "product_name_length",
            "product_description_lenght": "product_description_length",
        })
        used = set(products["product_category_name"].dropna())
        missing = sorted(used - set(cats["product_category_name"]))
        if missing:
            extra = pd.DataFrame({
                "product_category_name": missing,
                "product_category_name_english": [EXTRA_CATEGORIES.get(m, m) for m in missing],
            })
            cats = pd.concat([cats, extra], ignore_index=True)
            print(f"  added {len(missing)} categories missing from translation: {missing}")
        copy_df(conn, "product_categories", cats)

        int_cols = ["product_name_length", "product_description_length", "product_photos_qty",
                    "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]
        products[int_cols] = products[int_cols].astype("Int64")
        copy_df(conn, "products", products)

        customers = read("olist_customers_dataset")
        copy_df(conn, "customers", customers)
        sellers = read("olist_sellers_dataset")
        copy_df(conn, "sellers", sellers)

        # geolocation: 1M rows -> one row per zip prefix
        geo = read("olist_geolocation_dataset")
        key = "geolocation_zip_code_prefix"
        coords = geo.groupby(key)[["geolocation_lat", "geolocation_lng"]].mean().reset_index()
        top_city = (geo.groupby([key, "geolocation_city", "geolocation_state"]).size()
                    .reset_index(name="n").sort_values("n", ascending=False)
                    .drop_duplicates(key)[[key, "geolocation_city", "geolocation_state"]])
        geo_zip = coords.merge(top_city, on=key)
        geo_zip.columns = ["zip_prefix", "lat", "lng", "city", "state"]
        copy_df(conn, "geolocation_zip", geo_zip)

        print("Loading orders and children...")
        ts_cols = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
                   "order_delivered_customer_date", "order_estimated_delivery_date"]
        orders = read("olist_orders_dataset", parse_dates=ts_cols)
        orders = drop_orphans(orders, "customer_id", set(customers["customer_id"]), "orders")
        copy_df(conn, "orders", orders)
        order_ids = set(orders["order_id"])

        items = read("olist_order_items_dataset", parse_dates=["shipping_limit_date"])
        items = drop_orphans(items, "order_id", order_ids, "order_items")
        items = drop_orphans(items, "product_id", set(products["product_id"]), "order_items")
        items = drop_orphans(items, "seller_id", set(sellers["seller_id"]), "order_items")
        copy_df(conn, "order_items", items)

        pay = read("olist_order_payments_dataset")
        pay = drop_orphans(pay, "order_id", order_ids, "order_payments")
        copy_df(conn, "order_payments", pay)

        rev = read("olist_order_reviews_dataset",
                   parse_dates=["review_creation_date", "review_answer_timestamp"])
        rev = drop_orphans(rev, "order_id", order_ids, "order_reviews")
        copy_df(conn, "order_reviews", rev)  # review_pk auto-filled by BIGSERIAL

        print("Adding foreign keys and indexes...")
        conn.execute(open("sql/constraints.sql", encoding="utf-8").read())
        conn.execute("ANALYZE")

        print("\nRow counts:")
        for t in ["customers", "orders", "order_items", "order_payments", "order_reviews",
                  "products", "product_categories", "sellers", "geolocation_zip"]:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:<20} {n:>8}")


if __name__ == "__main__":
    main()
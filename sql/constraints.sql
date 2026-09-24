ALTER TABLE products       ADD FOREIGN KEY (product_category_name) REFERENCES product_categories;
ALTER TABLE orders         ADD FOREIGN KEY (customer_id) REFERENCES customers;
ALTER TABLE order_items    ADD FOREIGN KEY (order_id)    REFERENCES orders;
ALTER TABLE order_items    ADD FOREIGN KEY (product_id)  REFERENCES products;
ALTER TABLE order_items    ADD FOREIGN KEY (seller_id)   REFERENCES sellers;
ALTER TABLE order_payments ADD FOREIGN KEY (order_id)    REFERENCES orders;
ALTER TABLE order_reviews  ADD FOREIGN KEY (order_id)    REFERENCES orders;

CREATE INDEX idx_orders_customer   ON orders (customer_id);
CREATE INDEX idx_orders_purchase   ON orders (order_purchase_timestamp);
CREATE INDEX idx_orders_status     ON orders (order_status);
CREATE INDEX idx_items_product     ON order_items (product_id);
CREATE INDEX idx_items_seller      ON order_items (seller_id);
CREATE INDEX idx_payments_type     ON order_payments (payment_type);
CREATE INDEX idx_reviews_order     ON order_reviews (order_id);
CREATE INDEX idx_customers_unique  ON customers (customer_unique_id);
CREATE INDEX idx_customers_state   ON customers (customer_state);
CREATE INDEX idx_sellers_state     ON sellers (seller_state);
CREATE INDEX idx_products_category ON products (product_category_name);
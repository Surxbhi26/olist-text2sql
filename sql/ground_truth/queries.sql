-- ### Q01 | easy | How many orders are there for each order status?
SELECT order_status, COUNT(*) AS order_count
FROM orders
GROUP BY order_status
ORDER BY order_count DESC;

-- ### Q02 | easy | What are the top 10 product categories by revenue?
SELECT COALESCE(pc.product_category_name_english, p.product_category_name) AS category,
       ROUND(SUM(oi.price), 2) AS revenue
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_categories pc ON pc.product_category_name = p.product_category_name
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1
ORDER BY revenue DESC
LIMIT 10;

-- ### Q03 | easy | What is the average review score?
SELECT ROUND(AVG(review_score), 2) AS avg_review_score
FROM order_reviews;

-- ### Q04 | easy | Which 10 states have the most unique customers?
SELECT customer_state, COUNT(DISTINCT customer_unique_id) AS unique_customers
FROM customers
GROUP BY customer_state
ORDER BY unique_customers DESC
LIMIT 10;

-- ### Q05 | easy | How many sellers are there in each state?
SELECT seller_state, COUNT(*) AS seller_count
FROM sellers
GROUP BY seller_state
ORDER BY seller_count DESC;

-- ### Q06 | easy | What is the average item price and average freight value?
SELECT ROUND(AVG(price), 2) AS avg_price, ROUND(AVG(freight_value), 2) AS avg_freight
FROM order_items;

-- ### Q07 | medium | What percentage of customers are repeat customers?
SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE order_count >= 2) / COUNT(*), 2) AS repeat_customer_pct
FROM (
    SELECT c.customer_unique_id, COUNT(*) AS order_count
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
    GROUP BY c.customer_unique_id
) t;

-- ### Q08 | medium | What is the average delivery delay in days versus the estimated date, by customer state?
SELECT c.customer_state,
       ROUND(AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_estimated_delivery_date)) / 86400)::numeric, 2) AS avg_delay_days
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delay_days DESC;

-- ### Q09 | medium | What is the share of each payment type by month?
WITH pm AS (
    SELECT DATE_TRUNC('month', o.order_purchase_timestamp)::date AS month,
           p.payment_type,
           COUNT(*) AS payments
    FROM order_payments p
    JOIN orders o ON o.order_id = p.order_id
    GROUP BY 1, 2
)
SELECT month, payment_type, payments,
       ROUND(100.0 * payments / SUM(payments) OVER (PARTITION BY month), 2) AS share_pct
FROM pm
ORDER BY month, share_pct DESC;

-- ### Q10 | medium | What is the monthly revenue and its month-over-month growth?
WITH monthly AS (
    SELECT DATE_TRUNC('month', o.order_purchase_timestamp)::date AS month, SUM(oi.price) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY 1
)
SELECT month,
       ROUND(revenue, 2) AS revenue,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month)) / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS mom_growth_pct
FROM monthly
ORDER BY month;

-- ### Q11 | medium | What is the average order value?
SELECT ROUND(AVG(order_total), 2) AS avg_order_value
FROM (
    SELECT oi.order_id, SUM(oi.price) AS order_total
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY oi.order_id
) t;

-- ### Q12 | medium | What is the average delivery time in days from purchase to delivery, by customer state?
SELECT c.customer_state,
       ROUND(AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400)::numeric, 1) AS avg_delivery_days
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY avg_delivery_days DESC;

-- ### Q13 | medium | Who are the top 10 sellers by revenue?
SELECT oi.seller_id, ROUND(SUM(oi.price), 2) AS revenue
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY oi.seller_id
ORDER BY revenue DESC
LIMIT 10;

-- ### Q14 | medium | Which 10 product categories have the lowest average review score, among categories with at least 100 reviews?
SELECT pc.product_category_name_english AS category,
       ROUND(AVG(r.review_score), 2) AS avg_score,
       COUNT(*) AS review_count
FROM order_reviews r
JOIN order_items oi ON oi.order_id = r.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN product_categories pc ON pc.product_category_name = p.product_category_name
GROUP BY pc.product_category_name_english
HAVING COUNT(*) >= 100
ORDER BY avg_score ASC
LIMIT 10;

-- ### Q15 | hard | Which sellers have above-average revenue but below-average review scores?
WITH seller_rev AS (
    SELECT oi.seller_id, SUM(oi.price) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY oi.seller_id
),
seller_score AS (
    SELECT s.seller_id, AVG(r.review_score) AS avg_score
    FROM (SELECT DISTINCT seller_id, order_id FROM order_items) s
    JOIN order_reviews r ON r.order_id = s.order_id
    GROUP BY s.seller_id
)
SELECT sr.seller_id, ROUND(sr.revenue, 2) AS revenue, ROUND(ss.avg_score, 2) AS avg_score
FROM seller_rev sr
JOIN seller_score ss ON ss.seller_id = sr.seller_id
WHERE sr.revenue > (SELECT AVG(revenue) FROM seller_rev)
  AND ss.avg_score < (SELECT AVG(avg_score) FROM seller_score)
ORDER BY sr.revenue DESC;

-- ### Q16 | hard | On average, how many days pass between a customer's first and second order?
WITH ranked AS (
    SELECT c.customer_unique_id, o.order_purchase_timestamp AS ts,
           ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id ORDER BY o.order_purchase_timestamp) AS rn
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
),
firsts AS (
    SELECT customer_unique_id,
           MIN(ts) FILTER (WHERE rn = 1) AS first_ts,
           MIN(ts) FILTER (WHERE rn = 2) AS second_ts
    FROM ranked
    GROUP BY customer_unique_id
)
SELECT ROUND(AVG(EXTRACT(EPOCH FROM (second_ts - first_ts)) / 86400)::numeric, 1) AS avg_days_to_second_order
FROM firsts
WHERE second_ts IS NOT NULL;

-- ### Q17 | hard | Which 10 category and customer state combinations have the highest late-delivery rate, with at least 50 delivered orders?
SELECT pc.product_category_name_english AS category,
       c.customer_state,
       COUNT(DISTINCT o.order_id) AS delivered_orders,
       ROUND(100.0 * COUNT(DISTINCT o.order_id) FILTER (WHERE o.order_delivered_customer_date > o.order_estimated_delivery_date)
             / COUNT(DISTINCT o.order_id), 2) AS late_pct
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN product_categories pc ON pc.product_category_name = p.product_category_name
WHERE o.order_delivered_customer_date IS NOT NULL
GROUP BY pc.product_category_name_english, c.customer_state
HAVING COUNT(DISTINCT o.order_id) >= 50
ORDER BY late_pct DESC
LIMIT 10;

-- ### Q18 | hard | What is the top revenue category in each customer state?
WITH cat_state AS (
    SELECT c.customer_state, pc.product_category_name_english AS category,
           SUM(oi.price) AS revenue,
           RANK() OVER (PARTITION BY c.customer_state ORDER BY SUM(oi.price) DESC) AS rnk
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
    JOIN customers c ON c.customer_id = o.customer_id
    JOIN products p ON p.product_id = oi.product_id
    JOIN product_categories pc ON pc.product_category_name = p.product_category_name
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY c.customer_state, pc.product_category_name_english
)
SELECT customer_state, category, ROUND(revenue, 2) AS revenue
FROM cat_state
WHERE rnk = 1
ORDER BY customer_state;

-- ### Q19 | hard | How many active customers are there? (active = ordered in the last 90 days of the dataset)
SELECT COUNT(DISTINCT c.customer_unique_id) AS active_customers
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_purchase_timestamp > (SELECT MAX(order_purchase_timestamp) FROM orders) - INTERVAL '90 days';

-- ### Q20 | hard | How many customers gave their first order a review score of 1 or 2 and never ordered again?
WITH ranked AS (
    SELECT c.customer_unique_id, o.order_id,
           ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id ORDER BY o.order_purchase_timestamp) AS rn,
           COUNT(*) OVER (PARTITION BY c.customer_unique_id) AS total_orders
    FROM orders o
    JOIN customers c ON c.customer_id = o.customer_id
)
SELECT COUNT(DISTINCT r.customer_unique_id) AS churned_unhappy_customers
FROM ranked r
JOIN order_reviews rv ON rv.order_id = r.order_id
WHERE r.rn = 1 AND r.total_orders = 1 AND rv.review_score <= 2;

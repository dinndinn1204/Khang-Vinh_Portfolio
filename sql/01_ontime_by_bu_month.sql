-- On-time delivery rate and average lead time per business unit and month (warehouse_orders)
WITH o AS (
    SELECT business_unit,
           substr(order_date, 1, 7)                                          AS month,
           julianday(delivered_date) - julianday(order_date)                 AS lead_days,
           CASE WHEN delivered_date <= promised_date THEN 1 ELSE 0 END       AS on_time
    FROM warehouse_orders
)
SELECT month,
       business_unit,
       COUNT(*)                         AS orders,
       ROUND(100.0 * AVG(on_time), 1)   AS on_time_pct,
       ROUND(AVG(lead_days), 2)         AS avg_lead_days
FROM o
GROUP BY month, business_unit
ORDER BY month, business_unit;

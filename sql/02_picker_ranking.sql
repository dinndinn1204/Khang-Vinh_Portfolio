-- Picker productivity: lines picked per working day, on-time share, rank and gap to the team median
WITH daily AS (
    SELECT picker_id, order_date, SUM(lines) AS lines, COUNT(*) AS orders,
           SUM(CASE WHEN delivered_date <= promised_date THEN 1 ELSE 0 END) AS on_time
    FROM warehouse_orders
    GROUP BY picker_id, order_date
), p AS (
    SELECT picker_id,
           COUNT(*)                              AS days_worked,
           ROUND(AVG(lines), 1)                  AS lines_per_day,
           ROUND(100.0 * SUM(on_time) / SUM(orders), 1) AS on_time_pct
    FROM daily
    GROUP BY picker_id
)
SELECT picker_id, days_worked, lines_per_day, on_time_pct,
       RANK() OVER (ORDER BY lines_per_day DESC)                         AS rank_volume,
       RANK() OVER (ORDER BY on_time_pct DESC)                           AS rank_on_time,
       ROUND(lines_per_day - AVG(lines_per_day) OVER (), 1)              AS vs_team_avg
FROM p
ORDER BY rank_volume;

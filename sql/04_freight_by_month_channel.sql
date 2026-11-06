-- Monthly freight, bikes and cost per bike by channel (freight_priced = shipments after pricing)
SELECT substr(picked_up, 1, 7)                         AS month,
       channel,
       COUNT(*)                                        AS trips,
       SUM(bikes)                                      AS bikes,
       SUM(freight_vnd)                                AS freight_vnd,
       ROUND(1.0 * SUM(freight_vnd) / SUM(bikes), 0)   AS vnd_per_bike,
       ROUND(100.0 * SUM(freight_vnd) / SUM(SUM(freight_vnd)) OVER (PARTITION BY substr(picked_up, 1, 7)), 1) AS share_of_month_pct
FROM freight_priced
GROUP BY month, channel
ORDER BY month, channel;

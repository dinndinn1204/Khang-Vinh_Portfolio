-- Pareto of delivery issues: count per reason and cumulative share
WITH r AS (
    SELECT issue_reason, COUNT(*) AS issues
    FROM warehouse_orders
    WHERE issue_reason <> ''
    GROUP BY issue_reason
)
SELECT issue_reason, issues,
       ROUND(100.0 * issues / SUM(issues) OVER (), 1)                                   AS share_pct,
       ROUND(100.0 * SUM(issues) OVER (ORDER BY issues DESC ROWS UNBOUNDED PRECEDING)
                   / SUM(issues) OVER (), 1)                                            AS cumulative_pct
FROM r
ORDER BY issues DESC;

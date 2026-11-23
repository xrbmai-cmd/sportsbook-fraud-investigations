WITH eligible AS (          -- accounts created before W, with a successful login in W
  SELECT a.account_id FROM case01.accounts a
  WHERE a.created_at < TIMESTAMP '2026-08-15 13:00:00'
    AND EXISTS (SELECT 1 FROM case01.account_access x
                WHERE x.account_id = a.account_id AND x.event_type = 'login' AND x.success
                  AND x.event_time >= TIMESTAMP '2026-08-15 13:00:00'
                  AND x.event_time <  TIMESTAMP '2026-09-14 13:00:00')
),
flagged AS (                -- a successful login in W from a device with no event before W
  SELECT DISTINCT x.account_id FROM case01.account_access x
  WHERE x.event_type = 'login' AND x.success
    AND x.event_time >= TIMESTAMP '2026-08-15 13:00:00'
    AND x.event_time <  TIMESTAMP '2026-09-14 13:00:00'
    AND NOT EXISTS (SELECT 1 FROM case01.account_access y
                    WHERE y.account_id = x.account_id AND y.device_id = x.device_id
                      AND y.event_time < TIMESTAMP '2026-08-15 13:00:00')
)
SELECT COUNT(*) AS eligible,
       SUM(CASE WHEN e.account_id IN (SELECT account_id FROM flagged) THEN 1 ELSE 0 END) AS flagged,
       ROUND(100.0 * SUM(CASE WHEN e.account_id IN (SELECT account_id FROM flagged) THEN 1 ELSE 0 END)
             / COUNT(*), 1) AS flagged_pct
FROM eligible e;

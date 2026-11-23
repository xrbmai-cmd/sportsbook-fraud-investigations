# Walkthrough: how common is a new device?

A login from a new device looks suspicious. Before you treat it as evidence, measure how common it is among
comparable accounts. This walkthrough does that on the public sample, in DuckDB, in a few minutes.

## 1. Load the sample

The sample is seven CSV tables in `sample/`, each with a BigQuery load schema in `sample/schema/`. Money columns are
exact decimals and timestamps are UTC, written `YYYY-MM-DD HH:MM:SS UTC`.

```python
import duckdb, json

TYPES = {"STRING": "VARCHAR", "TIMESTAMP": "TIMESTAMP", "NUMERIC": "DECIMAL(38,9)",
         "INTEGER": "BIGINT", "BOOLEAN": "BOOLEAN"}
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
con.execute("CREATE SCHEMA case01")
for t in ["accounts", "account_access", "payments", "wallet_ledger", "bets", "events", "disputes"]:
    cols = {c["name"]: TYPES[c["type"]] for c in json.load(open(f"sample/schema/{t}.json"))}
    con.execute(f"""CREATE TABLE case01.{t} AS SELECT * FROM read_csv('sample/{t}.csv', header=true,
        timestampformat='%Y-%m-%d %H:%M:%S UTC', nullstr='', columns={json.dumps(cols)})""")
```

Row counts after loading:

| Table | Rows |
| --- | --- |
| accounts | 120 |
| account_access | 4,424 |
| payments | 1,464 |
| wallet_ledger | 20,948 |
| bets | 13,306 |
| events | 1,776 |
| disputes | 13 |

## 2. Define the comparison group and the indicator

- **Comparable accounts:** created before the window starts (2026-08-15 13:00 UTC) and with at least one successful
  login inside it. An account that could not have shown the indicator does not belong in the denominator.
- **The indicator:** a successful login inside the window from a device the account had never used before the window.
  "Never used before" means anywhere in the account's history, not only in recent weeks.
- **The window:** from 2026-08-15 13:00 UTC up to the cutoff, 2026-09-14 13:00 UTC, start included and end excluded.

## 3. Measure it

The query is standard SQL that runs as it is in BigQuery and in DuckDB:

```sql
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
```

```python
print(con.execute(open("walkthrough.sql").read()).fetchall())
```

On the sample it returns:

| eligible | flagged | flagged_pct |
| --- | --- | --- |
| 90 | 25 | 27.8 |

## 4. Read it

25 of 90 comparable accounts logged in from a new device in the window (27.8%). In this population a new
device is common, so on its own it says little about any one account. Write a rate this way every time: flagged out
of eligible, plus the percentage, and put the account you are investigating beside the rate, never inside it.

The cases in Sportsbook Fraud Investigations ask this kind of question about five indicators and two comparison
groups, then ask what the evidence supports and what to do about it.

"""Statistical acceptance criteria and data profile for a generated Case 01 dataset (Step 1 data report).

Usage: python3 engine/report.py <buyer_dir> [<designer_dir>] [--json]
Every figure is computed from buyer files. With a designer folder that lists the batch accounts (case_accounts.csv),
base-rate populations exclude them, as the spec requires, and the queue criterion covers the full queue (10 to 15).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "assertions"))
from run_assertions import load  # noqa: E402

R = "TIMESTAMP '2026-09-14 13:00:00'"
W = "TIMESTAMP '2026-08-15 13:00:00'"
MAT = "TIMESTAMP '2026-07-16 13:00:00'"

CRITERIA = [
    # name, query returning one number, low, high
    ("Eligible accounts in P_all", """
        SELECT COUNT(*) FROM case01.accounts a
        WHERE a.created_at < {W} AND a.account_id NOT IN (SELECT account_id FROM batch)
          AND EXISTS (SELECT 1 FROM case01.account_access x WHERE x.account_id = a.account_id
                      AND x.event_type = 'login' AND x.success AND x.event_time >= {W} AND x.event_time < {R})""", 200, None),
    ("I1 rate in P_all (%)", "SELECT 100.0 * AVG(i1::INT) FROM ind", 25, 35),
    ("I2 rate in P_all (%)", "SELECT 100.0 * AVG(i2::INT) FROM ind", 5, 10),
    ("Mature deposits", """
        SELECT COUNT(*) FROM case01.payments WHERE payment_type = 'deposit' AND status = 'captured' AND processed_at < {MAT}""", 1500, None),
    ("Mature deposits disputed", """
        SELECT COUNT(*) FROM case01.disputes d JOIN case01.payments p USING (payment_id) WHERE p.processed_at < {MAT}""", 15, None),
    ("R1 dispute rate on mature deposits (%)", """
        SELECT 100.0 * (SELECT COUNT(*) FROM case01.disputes d JOIN case01.payments p USING (payment_id) WHERE p.processed_at < {MAT})
             / (SELECT COUNT(*) FROM case01.payments WHERE payment_type = 'deposit' AND status = 'captured' AND processed_at < {MAT})""", 0.5, 1.5),
    ("QUEUE", """
        SELECT COUNT(*) FROM (SELECT account_id FROM case01.disputes WHERE received_at >= {W} AND received_at < {R}
                              GROUP BY account_id HAVING SUM(amount) >= 80)""", None, None),
    ("Background accounts with complete pre-incident features", """
        SELECT COUNT(*) FROM case01.accounts a
        WHERE a.created_at < {W} AND a.account_id NOT IN (SELECT account_id FROM batch)
          AND (SELECT COUNT(*) FROM case01.payments p WHERE p.account_id = a.account_id AND p.payment_type = 'deposit' AND p.status = 'captured') >= 2
          AND (SELECT COUNT(*) FROM case01.bets b WHERE b.account_id = a.account_id) >= 5""", 200, None),
]

INDICATORS = """
CREATE OR REPLACE TEMP TABLE ind AS
WITH elig AS (
  SELECT a.account_id FROM case01.accounts a
  WHERE a.created_at < {W} AND a.account_id NOT IN (SELECT account_id FROM batch)
    AND EXISTS (SELECT 1 FROM case01.account_access x WHERE x.account_id = a.account_id
                AND x.event_type = 'login' AND x.success AND x.event_time >= {W} AND x.event_time < {R})
),
logins AS (
  SELECT x.*,
         ROW_NUMBER() OVER (PARTITION BY account_id, device_id ORDER BY event_time) AS dev_n,
         ROW_NUMBER() OVER (PARTITION BY account_id, ip_country ORDER BY event_time) AS ctry_n
  FROM case01.account_access x
),
first_dev AS (
  SELECT account_id, event_time FROM logins
  WHERE event_type = 'login' AND success AND event_time >= {W} AND event_time < {R}
    AND NOT EXISTS (SELECT 1 FROM case01.account_access y WHERE y.account_id = logins.account_id
                    AND y.device_id = logins.device_id AND y.event_time < {W})
),
first_ctry AS (
  SELECT DISTINCT account_id FROM logins
  WHERE event_type = 'login' AND success AND event_time >= {W} AND event_time < {R}
    AND NOT EXISTS (SELECT 1 FROM case01.account_access y WHERE y.account_id = logins.account_id
                    AND y.ip_country = logins.ip_country AND y.event_time < {W})
),
cred AS (
  SELECT account_id, event_time FROM case01.account_access
  WHERE event_type IN ('password_reset', 'email_change')
)
SELECT e.account_id,
       e.account_id IN (SELECT account_id FROM first_dev) AS i1,
       e.account_id IN (SELECT account_id FROM first_ctry) AS i2,
       EXISTS (SELECT 1 FROM first_dev f JOIN cred c ON c.account_id = f.account_id
               WHERE f.account_id = e.account_id AND c.event_time >= f.event_time
                 AND c.event_time < f.event_time + INTERVAL 24 HOUR AND c.event_time < {R}) AS i3
FROM elig e
"""

PROFILE = [
    ("Accounts", "SELECT COUNT(*) FROM case01.accounts"),
    ("Events (all states)", "SELECT COUNT(*) FROM case01.events"),
    ("Events by status", "SELECT STRING_AGG(status || ' ' || n, ', ') FROM (SELECT status, COUNT(*) n FROM case01.events GROUP BY 1 ORDER BY 1)"),
    ("Bets", "SELECT COUNT(*) FROM case01.bets"),
    ("Bets by status", "SELECT STRING_AGG(status || ' ' || n, ', ') FROM (SELECT status, COUNT(*) n FROM case01.bets GROUP BY 1 ORDER BY 1)"),
    ("In-play share of bets (%)", """SELECT ROUND(100.0 * AVG((b.placed_at >= e.scheduled_start)::INT), 1)
        FROM case01.bets b JOIN case01.events e USING (event_id)"""),
    ("House result on settled bets (%)", """SELECT ROUND(100.0 * (SUM(stake) - SUM(payout)) / SUM(stake), 1)
        FROM case01.bets WHERE status IN ('won', 'lost')"""),
    ("Payments", "SELECT COUNT(*) FROM case01.payments"),
    ("Payments by type and status", """SELECT STRING_AGG(payment_type || '/' || status || ' ' || n, ', ')
        FROM (SELECT payment_type, status, COUNT(*) n FROM case01.payments GROUP BY 1, 2 ORDER BY 1, 2)"""),
    ("Declined share of deposit attempts (%)", """SELECT ROUND(100.0 * AVG((status = 'declined')::INT), 1)
        FROM case01.payments WHERE payment_type = 'deposit'"""),
    ("Preset share of deposits (%)", """SELECT ROUND(100.0 * AVG((amount IN (10, 20, 25, 50, 100, 200, 500))::INT), 1)
        FROM case01.payments WHERE payment_type = 'deposit'"""),
    ("Median deposit (USD)", "SELECT MEDIAN(amount) FROM case01.payments WHERE payment_type = 'deposit' AND status = 'captured'"),
    ("Ledger entries", "SELECT COUNT(*) FROM case01.wallet_ledger"),
    ("Access events", "SELECT COUNT(*) FROM case01.account_access"),
    ("Access events by type", """SELECT STRING_AGG(event_type || ' ' || n, ', ')
        FROM (SELECT event_type || CASE WHEN event_type = 'login' AND NOT success THEN ' (failed)' ELSE '' END AS event_type,
                     COUNT(*) n FROM case01.account_access GROUP BY 1 ORDER BY 1)"""),
    ("Accounts with any email change", "SELECT COUNT(DISTINCT account_id) FROM case01.account_access WHERE event_type = 'email_change'"),
    ("Accounts with any password reset", "SELECT COUNT(DISTINCT account_id) FROM case01.account_access WHERE event_type = 'password_reset'"),
    ("Devices shared by two accounts", """SELECT COUNT(*) FROM (SELECT device_id FROM case01.account_access GROUP BY 1
        HAVING COUNT(DISTINCT account_id) > 1)"""),
    ("Accounts with a travel login (any time)", """SELECT COUNT(DISTINCT x.account_id) FROM case01.account_access x
        JOIN case01.accounts a USING (account_id) WHERE x.ip_country != a.kyc_country"""),
    ("Accounts never KYC-verified", "SELECT COUNT(*) FROM case01.accounts WHERE kyc_verified_at IS NULL"),
    ("Accounts by status", "SELECT STRING_AGG(status || ' ' || n, ', ') FROM (SELECT status, COUNT(*) n FROM case01.accounts GROUP BY 1 ORDER BY 1)"),
    ("Disputes", "SELECT COUNT(*) FROM case01.disputes"),
    ("Disputes by reason", "SELECT STRING_AGG(reason_code || ' ' || n, ', ') FROM (SELECT reason_code, COUNT(*) n FROM case01.disputes GROUP BY 1 ORDER BY 1)"),
    ("Disputes by status", "SELECT STRING_AGG(status || ' ' || n, ', ') FROM (SELECT status, COUNT(*) n FROM case01.disputes GROUP BY 1 ORDER BY 1)"),
    ("Dispute lag, deposit to receipt (median days)", """SELECT ROUND(MEDIAN(date_diff('second', p.processed_at, d.received_at) / 86400.0), 1)
        FROM case01.disputes d JOIN case01.payments p USING (payment_id)"""),
    ("Disputes received in W", "SELECT COUNT(*) FROM case01.disputes WHERE received_at >= {W} AND received_at < {R}"),
    ("I3 rate in P_all (%)", "SELECT ROUND(100.0 * AVG(i3::INT), 1) FROM ind"),
    ("Available balance at R, all accounts (USD)", "SELECT SUM(amount) FROM case01.wallet_ledger"),
    ("Pending withdrawals at R", "SELECT COUNT(*) FROM case01.payments WHERE payment_type = 'withdrawal' AND status = 'pending'"),
    ("Open bets at R", "SELECT COUNT(*) FROM case01.bets WHERE status = 'open'"),
]


def run(buyer_dir, designer_dir=None):
    import duckdb
    con = duckdb.connect()
    load(con, buyer_dir, None)
    batch = os.path.join(designer_dir, "case_accounts.csv") if designer_dir else None
    with_cases = bool(batch and os.path.exists(batch))
    if with_cases:
        con.execute(f"CREATE TEMP TABLE batch AS SELECT account_id FROM read_csv('{batch}', header=true, all_varchar=true)")
    else:
        con.execute("CREATE TEMP TABLE batch (account_id VARCHAR)")
    fmt = dict(W=W, R=R, MAT=MAT)
    con.execute(INDICATORS.format(**fmt))
    crit = []
    for name, q, lo, hi in CRITERIA:
        if name == "QUEUE":
            name, lo, hi = (("Queue size at R (full queue)", 10, 15) if with_cases else
                            ("Queue size at R, natural background only (cases and planted accounts add about 7)", 3, 8))
        v = con.execute(q.format(**fmt)).fetchone()[0]
        v = round(float(v), 2) if v is not None else None
        ok = v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)
        band = f"{lo if lo is not None else ''} to {hi if hi is not None else ''}".strip()
        crit.append({"criterion": name, "value": v, "band": band, "pass": ok})
    prof = []
    for name, q in PROFILE:
        v = con.execute(q.format(**fmt)).fetchone()[0]
        prof.append({"measure": name, "value": float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, int) else v})
    return {"criteria": crit, "profile": prof}


if __name__ == "__main__":
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    res = run(pos[0], pos[1] if len(pos) > 1 else None)
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2, default=str))
    else:
        for c in res["criteria"]:
            print(f"{'PASS' if c['pass'] else 'FAIL'}  {c['criterion']}: {c['value']}  (band {c['band']})")
        print()
        for p in res["profile"]:
            print(f"  {p['measure']}: {p['value']}")
    failing = sum(not c["pass"] for c in res["criteria"])
    print(f"\n{failing} failing criterion(s)", file=sys.stderr)
    sys.exit(1 if failing else 0)

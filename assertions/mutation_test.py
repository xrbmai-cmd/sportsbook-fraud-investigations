"""Mutation test: inject one deliberate defect per assertion into a valid dataset and confirm that assertion fails.

Usage: python3 assertions/mutation_test.py <valid_buyer_dir> <valid_designer_dir> [--extra <sql> --mutations <py>]
A passing assertion suite proves nothing unless each assertion is shown to catch the defect it exists for.
"""
import csv
import os
import shutil
import sys
import tempfile

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_assertions import load, parse_blocks, to_duckdb, check_columns  # noqa: E402


def read(d, t):
    with open(os.path.join(d, f"{t}.csv"), newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def write(d, t, fields, rows):
    with open(os.path.join(d, f"{t}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def first(rows, **cond):
    for r in rows:
        if all((v(r[k]) if callable(v) else r[k] == v) for k, v in cond.items()):
            return r
    raise LookupError(cond)


def m_R1(d):
    f, rows = read(d, "accounts"); rows.append(dict(rows[0])); write(d, "accounts", f, rows)

def m_R2(d):
    f, rows = read(d, "bets"); rows[0]["event_id"] = "EVT-00000000"; write(d, "bets", f, rows)

def m_R3(d):
    f, rows = read(d, "bets")
    other = first(rows, account_id=lambda v: v != rows[0]["account_id"])
    rows[0]["session_id"] = other["session_id"]; write(d, "bets", f, rows)

def m_R4(d):
    f, rows = read(d, "wallet_ledger")
    r = first(rows, entry_type="stake"); r["payment_id"] = first(rows, entry_type="deposit_credit")["payment_id"]
    write(d, "wallet_ledger", f, rows)

def m_R5(d):
    f, rows = read(d, "disputes"); rows[0]["amount"] = "1.00"; write(d, "disputes", f, rows)

def m_R6(d):
    f, rows = read(d, "payments")
    first(rows, payment_type="withdrawal")["instrument_id"] = "EWAL-ZZZZZZZZ"; write(d, "payments", f, rows)

def m_T1(d):
    f, rows = read(d, "accounts"); rows[0]["kyc_verified_at"] = "2026-09-14 13:00:00 UTC"; write(d, "accounts", f, rows)

def m_T2(d):
    fa, accts = read(d, "accounts"); f, rows = read(d, "account_access")
    created = {a["account_id"]: a["created_at"] for a in accts}
    r = rows[0]; c = created[r["account_id"]]
    r["event_time"] = c[:8] + "%02d" % (int(c[8:10]) - 1) + c[10:] if int(c[8:10]) > 1 else "2026-03-02 00:00:01 UTC"
    if r["event_time"] < "2026-03-02":
        r["event_time"] = "2026-03-02 00:00:01 UTC"
    write(d, "account_access", f, rows)

def m_T3(d):
    f, rows = read(d, "payments")
    r = first(rows, payment_type="deposit", status="captured")
    r["processed_at"] = r["created_at"]; write(d, "payments", f, rows)

def m_T4(d):
    fp, pays = read(d, "payments"); f, rows = read(d, "accounts")
    acct = first(pays, payment_type="withdrawal")["account_id"]
    first(rows, account_id=acct)["kyc_verified_at"] = ""; write(d, "accounts", f, rows)

def m_T5(d):
    f, rows = read(d, "disputes"); rows[0]["received_at"] = rows[0]["filed_at"]; write(d, "disputes", f, rows)

def m_T6(d):
    fe, evs = read(d, "events"); f, rows = read(d, "bets")
    ended = {e["event_id"]: e["ended_at"] for e in evs}
    r = first(rows, status="lost")
    r["settled_at"] = r["placed_at"]; write(d, "bets", f, rows)

def m_T7(d):
    f, rows = read(d, "payments")
    dep = first(rows, payment_type="deposit", status="captured")
    rows.append(dict(dep, payment_id="PAY-REFUND01", payment_type="refund", parent_payment_id=dep["payment_id"],
                     session_id="", status="completed", created_at=dep["created_at"], processed_at=dep["processed_at"]))
    write(d, "payments", f, rows)

def m_T8(d):
    f, rows = read(d, "wallet_ledger")
    rows.sort(key=lambda r: int(r["entry_seq"]))
    a, b = rows[10], rows[-10]
    a["entry_seq"], b["entry_seq"] = b["entry_seq"], a["entry_seq"]
    write(d, "wallet_ledger", f, rows)

def m_F1(d):
    f, rows = read(d, "wallet_ledger")
    rows.sort(key=lambda r: int(r["entry_seq"]))
    r = first(rows, entry_type="withdrawal_hold"); r["amount"] = "-99999.00"
    write(d, "wallet_ledger", f, rows)

def m_F2(d):
    f, rows = read(d, "wallet_ledger")
    r = first(rows, entry_type="deposit_credit")
    rows.append(dict(r, entry_id="LED-DUPCRED1", entry_seq=str(max(int(x["entry_seq"]) for x in rows) + 1)))
    write(d, "wallet_ledger", f, rows)

def m_F3(d):
    f, rows = read(d, "wallet_ledger")
    rows.remove(first(rows, entry_type="deposit_credit")); write(d, "wallet_ledger", f, rows)

def m_F4(d):
    m_T7(d)

def m_F5(d):
    f, rows = read(d, "bets")
    r = first(rows, status="won"); r["payout"] = "%.2f" % (float(r["payout"]) + 1); write(d, "bets", f, rows)

def m_F6(d):
    f, rows = read(d, "bets")
    r = first(rows, status="lost"); r["status"] = "won"; write(d, "bets", f, rows)

def m_F7(d):
    f, rows = read(d, "wallet_ledger")
    rows.remove(first(rows, entry_type="withdrawal_hold")); write(d, "wallet_ledger", f, rows)

def m_F8(d):
    f, rows = read(d, "payments")
    deps = [r for r in rows if r["payment_type"] == "deposit" and r["status"] == "captured"]
    deps[1]["merchant_reference"] = deps[0]["merchant_reference"]; write(d, "payments", f, rows)

def m_F9(d):
    f, rows = read(d, "bets"); first(rows, status="lost")["stake"] = "0.50"; write(d, "bets", f, rows)

def m_S1(d):
    f, rows = read(d, "disputes")
    r = first(rows, status=lambda v: v != "open"); r["status"] = "open"; write(d, "disputes", f, rows)

def m_S2(d):
    f, rows = read(d, "events")
    r = first(rows, status="scheduled"); r["home_score"], r["away_score"] = "1", "0"; write(d, "events", f, rows)

def m_S3(d):
    fe, evs = read(d, "events"); f, rows = read(d, "bets")
    live = {e["event_id"] for e in evs if e["status"] in ("scheduled", "in_play")}
    r = first(rows, event_id=lambda v: v in live); r["status"] = "lost"; r["payout"] = "0.00"
    r["settled_at"] = r["placed_at"]
    write(d, "bets", f, rows)

def m_V1(d):
    f, rows = read(d, "accounts"); rows[0]["status"] = "suspended"; write(d, "accounts", f, rows)

def m_V2(d):
    f, rows = read(d, "account_access"); rows[0]["device_id"] = "DEV-123"; write(d, "account_access", f, rows)

def m_S4(d):
    f, rows = read(d, "events")
    f2 = [c for c in f if c != "away_score"]
    for r in rows:
        r.pop("away_score")
    write(d, "events", f2, rows)


def run_suite(buyer, designer):
    s4 = len(check_columns(buyer))
    if s4:
        return {"S4": s4}
    con = duckdb.connect()
    try:
        load(con, buyer, designer)
    except Exception as ex:
        return {"__load__": str(ex)}
    res = {}
    for b in [blk for path in [os.path.join(HERE, "assertions.sql")] + EXTRA_SQL for blk in parse_blocks(path)]:
        try:
            res[b["id"]] = len(con.execute(to_duckdb(b["sql"])).fetchall())
        except Exception as ex:
            res[b["id"]] = f"ERROR {ex}"
    res["S4"] = 0
    return res


EXTRA_SQL = []


def main():
    """Usage: mutation_test.py <buyer> <designer> [--extra <private.sql> --mutations <private_mutations.py>]"""
    argv = sys.argv[1:]
    opts = {argv[i]: argv[i + 1] for i in range(len(argv)) if argv[i].startswith("--")}
    buyer, designer = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))][:2]
    mutations = {k[2:]: v for k, v in globals().items() if k.startswith("m_")}
    if "--extra" in opts:
        EXTRA_SQL.append(opts["--extra"])
    if "--mutations" in opts:
        import importlib.util
        spec = importlib.util.spec_from_file_location("private_mutations", opts["--mutations"])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mutations.update(mod.mutations(designer))
    base = run_suite(buyer, designer)
    assert all(v == 0 for v in base.values()), f"baseline is not clean: {base}"
    caught = 0
    for aid, fn in mutations.items():
        tmp = tempfile.mkdtemp()
        shutil.copytree(buyer, os.path.join(tmp, "b"))
        fn(os.path.join(tmp, "b"))
        res = run_suite(os.path.join(tmp, "b"), designer)
        target = res.get(aid, res.get("__load__"))
        hit = isinstance(target, int) and target > 0
        caught += hit
        also = [k for k, v in res.items() if k != aid and v != 0]
        print(f"{aid:3} {'CAUGHT' if hit else 'MISSED'}  target={target}  also_failing={also}")
        shutil.rmtree(tmp)
    print(f"\n{caught}/{len(mutations)} deliberate defects caught by their own assertion")
    return 0 if caught == len(mutations) else 1


if __name__ == "__main__":
    sys.exit(main())

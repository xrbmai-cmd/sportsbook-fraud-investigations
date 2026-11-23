"""Run the Case 01 integrity assertions locally in DuckDB.

Usage: python3 assertions/run_assertions.py <buyer_dir> [<designer_dir>] [--extra <private assertions.sql>]

The assertions are written in BigQuery SQL (assertions.sql) and translated to DuckDB with sqlglot.
BigQuery remains the reference dialect; this runner is the fast local loop.
"""
import csv
import json
import os
import re
import sys

import duckdb
import sqlglot

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))
from schema import SCHEMA, DESIGNER_TABLES, duckdb_ddl  # noqa: E402


def parse_blocks(path):
    text = open(path, encoding="utf-8").read()
    parts = re.split(r"^-- @id ", text, flags=re.M)[1:]
    blocks = []
    for part in parts:
        lines = part.splitlines()
        aid = lines[0].strip()
        desc = next((l[len("-- @desc "):] for l in lines if l.startswith("-- @desc ")), "")
        scope = next((l[len("-- @scope "):].strip() for l in lines if l.startswith("-- @scope ")), "buyer")
        sql = "\n".join(l for l in lines[1:] if not l.startswith("-- @")).strip().rstrip(";")
        blocks.append({"id": aid, "desc": desc, "scope": scope, "sql": sql})
    return blocks


# BigQuery's TIMESTAMP_DIFF(a, b, unit) is the number of WHOLE units elapsed from b to a, truncated toward zero
# (observed natively on Nov 17: 4 days 3h 55m 46s is 5935 MINUTE, not 5936). sqlglot writes it as DuckDB's
# DATE_DIFF(unit, b, a), which counts unit BOUNDARIES crossed instead and runs one higher whenever the seconds part
# of b is later than that of a. to_duckdb therefore rewrites every TIMESTAMP_DIFF into exact microsecond arithmetic
# with BigQuery's meaning. solutions/test_timestamp_diff.py holds the regression test.
TIMESTAMP_DIFF_UNIT_US = {"MICROSECOND": 1, "MILLISECOND": 1_000, "SECOND": 1_000_000, "MINUTE": 60_000_000,
                          "HOUR": 3_600_000_000, "DAY": 86_400_000_000}


def _bigquery_timestamp_diff(node):
    unit = node.args["unit"].name.upper()
    if unit not in TIMESTAMP_DIFF_UNIT_US:
        raise ValueError(f"TIMESTAMP_DIFF unit {unit} has no exact DuckDB translation here")
    d = f"(epoch_us({node.this.sql(dialect='duckdb')}) - epoch_us({node.expression.sql(dialect='duckdb')}))"
    return sqlglot.parse_one(f"CAST(sign({d}) * (abs({d}) // {TIMESTAMP_DIFF_UNIT_US[unit]}) AS BIGINT)", read="duckdb")


def to_duckdb(sql):
    # DuckDB TIMESTAMP literals do not take a zone suffix; all data is UTC.
    sql = re.sub(r"TIMESTAMP '([0-9:\- ]+) UTC'", r"TIMESTAMP '\1'", sql)
    out = []
    for tree in sqlglot.parse(sql, read="bigquery"):
        if tree is None:
            continue
        while True:   # innermost first, so a nested TIMESTAMP_DIFF is never rendered with DuckDB's boundary meaning
            inner = [n for n in tree.find_all(sqlglot.exp.TimestampDiff)
                     if not any(isinstance(c, sqlglot.exp.TimestampDiff) for c in n.find_all(sqlglot.exp.TimestampDiff)
                                if c is not n)]
            if not inner:
                break
            for n in inner:
                replacement = _bigquery_timestamp_diff(n)
                if n is tree:
                    tree = replacement
                else:
                    n.replace(replacement)
        out.append(tree.sql(dialect="duckdb"))
    return ";\n".join(out)


def load(con, buyer_dir, designer_dir):
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE SCHEMA IF NOT EXISTS case01")
    con.execute("CREATE SCHEMA IF NOT EXISTS designer")
    for table, cols in SCHEMA.items():
        con.execute(duckdb_ddl("case01", table, cols))
        path = os.path.join(buyer_dir, f"{table}.csv")
        if os.path.exists(path):
            con.execute(
                f"INSERT INTO case01.{table} SELECT * FROM read_csv('{path}', header=true, "
                f"timestampformat='%Y-%m-%d %H:%M:%S UTC', nullstr='', "
                f"columns={json.dumps({c: _csv_type(t) for c, t, _ in cols})})"
            )
    for table, cols in DESIGNER_TABLES.items():
        con.execute(duckdb_ddl("designer", table, cols))
        if designer_dir:
            path = os.path.join(designer_dir, f"{table}.csv")
            if os.path.exists(path):
                con.execute(f"INSERT INTO designer.{table} SELECT * FROM read_csv('{path}', header=true, all_varchar=true)")
    # Extra designer tables declared by a private overlay (all text columns)
    extra = os.path.join(designer_dir, "extra_tables.json") if designer_dir else None
    if extra and os.path.exists(extra):
        for table, cols in json.load(open(extra, encoding="utf-8")).items():
            con.execute(f"CREATE OR REPLACE TABLE designer.{table} ({', '.join(c + ' VARCHAR' for c in cols)})")
            path = os.path.join(designer_dir, f"{table}.csv")
            con.execute(f"INSERT INTO designer.{table} SELECT * FROM read_csv('{path}', header=true, all_varchar=true, "
                        f"columns={json.dumps({c: 'VARCHAR' for c in cols})})")


def _csv_type(t):
    return {"STRING": "VARCHAR", "TIMESTAMP": "TIMESTAMP", "NUMERIC": "DECIMAL(38,9)",
            "INTEGER": "BIGINT", "BOOLEAN": "BOOLEAN"}[t]


def check_columns(buyer_dir):
    """S4: buyer file columns match the published schema exactly."""
    problems = []
    for table, cols in SCHEMA.items():
        path = os.path.join(buyer_dir, f"{table}.csv")
        if not os.path.exists(path):
            problems.append((table, "file missing"))
            continue
        with open(path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f))
        if header != [c for c, _, _ in cols]:
            problems.append((table, f"header {header}"))
    extra = [f for f in os.listdir(buyer_dir) if f.endswith(".csv") and f[:-4] not in SCHEMA]
    problems += [(f, "unexpected file") for f in extra]
    return problems


def assertion_files(argv):
    """assertions.sql, plus any private files passed with --extra <path>."""
    files = [os.path.join(HERE, "assertions.sql")]
    if "--extra" in argv:
        files.append(argv[argv.index("--extra") + 1])
    return files


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1) if a != "--extra" and sys.argv[i - 1] != "--extra"]
    buyer_dir = args[0]
    designer_dir = args[1] if len(args) > 1 else None
    s4 = check_columns(buyer_dir)
    if s4:  # files that do not match the schema cannot be loaded; report and stop
        for p in s4:
            print("    S4 sample:", p)
        print("S4   FAIL  Buyer file columns match the published schema exactly\n\n1 failing assertion(s)")
        return 1
    con = duckdb.connect()
    load(con, buyer_dir, designer_dir)
    blocks = [b for path in assertion_files(sys.argv) for b in parse_blocks(path)]
    failures = 0
    results = []
    for b in blocks:
        if b["scope"] == "designer" and not designer_dir:
            results.append((b["id"], "SKIP", 0, b["desc"]))
            continue
        try:
            rows = con.execute(to_duckdb(b["sql"])).fetchall()
        except Exception as ex:  # a broken assertion is a failure, never a pass
            results.append((b["id"], "ERROR", 0, f"{b['desc']} :: {ex}"))
            failures += 1
            continue
        status = "PASS" if not rows else "FAIL"
        failures += status == "FAIL"
        results.append((b["id"], status, len(rows), b["desc"]))
        if rows:
            for r in rows[:5]:
                print(f"    {b['id']} sample: {r}")
    results.append(("S4", "PASS" if not s4 else "FAIL", len(s4), "Buyer file columns match the published schema exactly"))
    failures += bool(s4)
    for aid, status, n, desc in results:
        print(f"{aid:4} {status:5} {n:6}  {desc}")
    print(f"\n{failures} failing assertion(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

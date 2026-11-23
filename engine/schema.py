"""Published buyer schema for Case 01 (Step 0 v2.1). Single source for BigQuery load schemas and local DuckDB tables."""

# (column, BigQuery load type, mode)
SCHEMA = {
    "accounts": [
        ("account_id", "STRING", "REQUIRED"),
        ("created_at", "TIMESTAMP", "REQUIRED"),
        ("kyc_country", "STRING", "REQUIRED"),
        ("kyc_verified_at", "TIMESTAMP", "NULLABLE"),
        ("status", "STRING", "REQUIRED"),
    ],
    "account_access": [
        ("access_id", "STRING", "REQUIRED"),
        ("account_id", "STRING", "REQUIRED"),
        ("event_time", "TIMESTAMP", "REQUIRED"),
        ("event_type", "STRING", "REQUIRED"),
        ("success", "BOOLEAN", "REQUIRED"),
        ("session_id", "STRING", "NULLABLE"),
        ("device_id", "STRING", "REQUIRED"),
        ("ip_token", "STRING", "REQUIRED"),
        ("ip_country", "STRING", "REQUIRED"),
        ("instrument_id", "STRING", "NULLABLE"),
    ],
    "payments": [
        ("payment_id", "STRING", "REQUIRED"),
        ("account_id", "STRING", "REQUIRED"),
        ("session_id", "STRING", "NULLABLE"),
        ("payment_type", "STRING", "REQUIRED"),
        ("merchant_reference", "STRING", "REQUIRED"),
        ("parent_payment_id", "STRING", "NULLABLE"),
        ("instrument_id", "STRING", "REQUIRED"),
        ("amount", "NUMERIC", "REQUIRED"),
        ("currency", "STRING", "REQUIRED"),
        ("status", "STRING", "REQUIRED"),
        ("created_at", "TIMESTAMP", "REQUIRED"),
        ("processed_at", "TIMESTAMP", "NULLABLE"),
    ],
    "wallet_ledger": [
        ("entry_id", "STRING", "REQUIRED"),
        ("entry_seq", "INTEGER", "REQUIRED"),
        ("account_id", "STRING", "REQUIRED"),
        ("entry_time", "TIMESTAMP", "REQUIRED"),
        ("entry_type", "STRING", "REQUIRED"),
        ("amount", "NUMERIC", "REQUIRED"),
        ("payment_id", "STRING", "NULLABLE"),
        ("bet_id", "STRING", "NULLABLE"),
    ],
    "bets": [
        ("bet_id", "STRING", "REQUIRED"),
        ("account_id", "STRING", "REQUIRED"),
        ("session_id", "STRING", "REQUIRED"),
        ("event_id", "STRING", "REQUIRED"),
        ("market", "STRING", "REQUIRED"),
        ("selection", "STRING", "REQUIRED"),
        ("odds", "NUMERIC", "REQUIRED"),
        ("stake", "NUMERIC", "REQUIRED"),
        ("placed_at", "TIMESTAMP", "REQUIRED"),
        ("status", "STRING", "REQUIRED"),
        ("settled_at", "TIMESTAMP", "NULLABLE"),
        ("payout", "NUMERIC", "NULLABLE"),
    ],
    "events": [
        ("event_id", "STRING", "REQUIRED"),
        ("sport", "STRING", "REQUIRED"),
        ("competition", "STRING", "REQUIRED"),
        ("home_team", "STRING", "REQUIRED"),
        ("away_team", "STRING", "REQUIRED"),
        ("scheduled_start", "TIMESTAMP", "REQUIRED"),
        ("status", "STRING", "REQUIRED"),
        ("ended_at", "TIMESTAMP", "NULLABLE"),
        ("home_score", "INTEGER", "NULLABLE"),
        ("away_score", "INTEGER", "NULLABLE"),
    ],
    "disputes": [
        ("dispute_id", "STRING", "REQUIRED"),
        ("payment_id", "STRING", "REQUIRED"),
        ("account_id", "STRING", "REQUIRED"),
        ("reason_code", "STRING", "REQUIRED"),
        ("amount", "NUMERIC", "REQUIRED"),
        ("filed_at", "TIMESTAMP", "REQUIRED"),
        ("received_at", "TIMESTAMP", "REQUIRED"),
        ("status", "STRING", "REQUIRED"),
        ("resolved_at", "TIMESTAMP", "NULLABLE"),
    ],
}

DUCKDB_TYPES = {
    "STRING": "VARCHAR",
    "TIMESTAMP": "TIMESTAMP",
    "NUMERIC": "DECIMAL(38,9)",
    "INTEGER": "BIGINT",
    "BOOLEAN": "BOOLEAN",
}

# Designer-only tables used by designer-scope assertions (none in the public engine).
DESIGNER_TABLES = {}


def bigquery_schema_json(table):
    return [{"name": c, "type": t, "mode": m} for c, t, m in SCHEMA[table]]


def duckdb_ddl(schema_name, table, columns):
    cols = ", ".join(f"{c} {DUCKDB_TYPES[t]}" for c, t, _ in columns)
    return f"CREATE OR REPLACE TABLE {schema_name}.{table} ({cols})"

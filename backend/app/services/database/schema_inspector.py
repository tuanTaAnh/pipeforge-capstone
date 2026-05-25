from __future__ import annotations

from typing import Any

from app.services.metadata.contract_loader import get_contract_dbt_source
from app.services.database.database_service import fetch_all, fetch_one, quote_identifier, table_exists


def inspect_table_schema(
    table_name: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not table_exists(table_name):
        raise RuntimeError(f"Table does not exist: {table_name}")

    safe_table = quote_identifier(table_name)

    columns = fetch_all(f"PRAGMA table_info({safe_table})")

    row_count_row = fetch_one(f"SELECT COUNT(*) AS row_count FROM {safe_table}")
    row_count = int(row_count_row["row_count"]) if row_count_row else 0

    sample_rows = fetch_all(f"SELECT * FROM {safe_table} LIMIT 5")

    dbt_source = get_contract_dbt_source(contract) if contract else "source('stripe', 'payments')"

    return {
        "source": table_name,
        "dbt_source": dbt_source,
        "row_count": row_count,
        "columns": [
            {
                "name": column["name"],
                "type": column["type"],
                "normalized_type": _normalize_sqlite_type(str(column["type"])),
                "not_null": bool(column["notnull"]),
                "primary_key": bool(column["pk"]),
            }
            for column in columns
        ],
        "sample_rows": sample_rows,
    }


def _normalize_sqlite_type(raw_type: str) -> str:
    value = raw_type.strip().lower()

    if not value:
        return "unknown"

    if "int" in value:
        return "integer"

    if any(token in value for token in ["real", "double", "float", "numeric", "decimal"]):
        return "real"

    if any(token in value for token in ["char", "text", "clob", "varchar"]):
        return "text"

    if "blob" in value:
        return "blob"

    return value
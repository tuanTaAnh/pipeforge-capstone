from __future__ import annotations

from typing import Any

from app.services.contract_loader import get_contract_columns
from app.services.database_service import fetch_all, fetch_one, quote_identifier


def run_quality_checks(
    table_name: str,
    schema: dict[str, Any],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    safe_table = quote_identifier(table_name)
    total_rows = int(schema["row_count"])

    if total_rows == 0:
        return [
            {
                "id": "issue_empty_table",
                "type": "empty_table",
                "severity": "must_answer",
                "column": None,
                "message": f"{table_name} has no rows.",
                "evidence": {"total_rows": 0},
                "affects": ["pipeline_generation"],
            }
        ]

    contract_columns = get_contract_columns(contract)
    actual_columns = _actual_column_map(schema)

    issues: list[dict[str, Any]] = []

    issues.extend(_check_schema_contract(contract_columns, actual_columns))
    issues.extend(_check_nullable_contract(safe_table, contract_columns, actual_columns, total_rows))
    issues.extend(_check_primary_keys(safe_table, contract_columns, actual_columns, total_rows))
    issues.extend(_check_valid_values(safe_table, contract_columns, actual_columns, total_rows))
    issues.extend(_check_column_checks(safe_table, contract_columns, actual_columns, total_rows))
    issues.extend(_check_business_rule_triggers(safe_table, contract, contract_columns, actual_columns, total_rows))

    return issues


def _actual_column_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        column["name"]: column
        for column in schema.get("columns", [])
        if isinstance(column, dict) and "name" in column
    }


def _check_schema_contract(
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for column_name, column_contract in contract_columns.items():
        if column_name not in actual_columns:
            findings.append(
                {
                    "id": f"issue_missing_column_{column_name}",
                    "type": "missing_required_column",
                    "severity": "must_answer",
                    "column": column_name,
                    "message": f"Expected column {column_name} is missing from the source table.",
                    "evidence": {
                        "expected_column": column_name,
                        "expected_type": column_contract.get("type"),
                    },
                    "affects": ["sql_model", "data_tests", "documentation"],
                }
            )
            continue

        expected_type = _normalize_contract_type(str(column_contract.get("type", "")))
        actual_type = str(actual_columns[column_name].get("normalized_type", "unknown"))

        if expected_type and actual_type != "unknown" and expected_type != actual_type:
            findings.append(
                {
                    "id": f"issue_type_mismatch_{column_name}",
                    "type": "type_mismatch",
                    "severity": "optional_review",
                    "column": column_name,
                    "message": (
                        f"Column {column_name} has type {actual_type}, "
                        f"but contract expects {expected_type}."
                    ),
                    "evidence": {
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                    },
                    "affects": ["sql_model", "data_tests"],
                }
            )

    extra_columns = [
        column_name
        for column_name in actual_columns
        if column_name not in contract_columns
    ]

    if extra_columns:
        findings.append(
            {
                "id": "finding_extra_columns",
                "type": "extra_columns",
                "severity": "info",
                "column": None,
                "message": f"Source contains extra columns not defined in the contract: {', '.join(extra_columns)}.",
                "evidence": {"extra_columns": extra_columns},
                "affects": ["documentation"],
            }
        )

    return findings


def _check_nullable_contract(
    safe_table: str,
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for column_name, column_contract in contract_columns.items():
        if column_name not in actual_columns:
            continue

        nullable = bool(column_contract.get("nullable", True))

        if nullable:
            continue

        safe_column = quote_identifier(column_name)

        row = fetch_one(
            f"""
            SELECT COUNT(*) AS null_count
            FROM {safe_table}
            WHERE {safe_column} IS NULL
            """
        )

        null_count = int(row["null_count"]) if row else 0

        if null_count == 0:
            continue

        null_rate = null_count / total_rows

        findings.append(
            {
                "id": f"issue_{column_name}_required_nulls",
                "type": "required_column_nulls",
                "severity": "must_answer",
                "column": column_name,
                "message": f"Required column {column_name} is null in {null_rate:.1%} of rows.",
                "evidence": {
                    "null_count": null_count,
                    "total_rows": total_rows,
                    "null_rate": round(null_rate, 4),
                    "contract_nullable": nullable,
                },
                "affects": _default_affects_for_column(column_name),
            }
        )

    return findings


def _check_primary_keys(
    safe_table: str,
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    primary_keys = [
        column_name
        for column_name, column_contract in contract_columns.items()
        if bool(column_contract.get("primary_key", False)) and column_name in actual_columns
    ]

    for column_name in primary_keys:
        safe_column = quote_identifier(column_name)

        duplicate_rows = fetch_all(
            f"""
            SELECT {safe_column} AS value, COUNT(*) AS duplicate_count
            FROM {safe_table}
            WHERE {safe_column} IS NOT NULL
            GROUP BY {safe_column}
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC
            LIMIT 10
            """
        )

        if duplicate_rows:
            findings.append(
                {
                    "id": f"issue_{column_name}_duplicates",
                    "type": "duplicate_key",
                    "severity": "must_answer",
                    "column": column_name,
                    "message": f"Primary key column {column_name} has duplicate value(s).",
                    "evidence": {
                        "duplicate_values": len(duplicate_rows),
                        "examples": duplicate_rows,
                        "total_rows": total_rows,
                    },
                    "affects": ["metric_logic", "sql_model", "data_tests"],
                }
            )
        else:
            findings.append(
                {
                    "id": f"finding_{column_name}_unique",
                    "type": "uniqueness",
                    "severity": "info",
                    "column": column_name,
                    "message": f"Primary key column {column_name} appears unique.",
                    "evidence": {
                        "duplicate_values": 0,
                        "total_rows": total_rows,
                    },
                    "affects": ["documentation"],
                }
            )

    return findings


def _check_valid_values(
    safe_table: str,
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for column_name, column_contract in contract_columns.items():
        valid_values = column_contract.get("valid_values")

        if not valid_values or column_name not in actual_columns:
            continue

        if not isinstance(valid_values, list):
            continue

        safe_column = quote_identifier(column_name)
        placeholders = ", ".join("?" for _ in valid_values)

        invalid_rows = fetch_all(
            f"""
            SELECT {safe_column} AS value, COUNT(*) AS row_count
            FROM {safe_table}
            WHERE {safe_column} IS NOT NULL
              AND {safe_column} NOT IN ({placeholders})
            GROUP BY {safe_column}
            ORDER BY row_count DESC
            """,
            tuple(valid_values),
        )

        if invalid_rows:
            invalid_count = sum(int(row["row_count"]) for row in invalid_rows)

            findings.append(
                {
                    "id": f"issue_{column_name}_invalid_values",
                    "type": "invalid_values",
                    "severity": "must_answer",
                    "column": column_name,
                    "message": f"{column_name} contains values outside the contract valid_values list.",
                    "evidence": {
                        "expected_values": valid_values,
                        "invalid_values": invalid_rows,
                        "invalid_count": invalid_count,
                        "total_rows": total_rows,
                    },
                    "affects": ["sql_model", "data_tests", "documentation"],
                }
            )
            continue

        observed = fetch_all(
            f"""
            SELECT DISTINCT {safe_column} AS value
            FROM {safe_table}
            WHERE {safe_column} IS NOT NULL
            ORDER BY {safe_column}
            """
        )

        findings.append(
            {
                "id": f"finding_{column_name}_accepted_values",
                "type": "accepted_values",
                "severity": "info",
                "column": column_name,
                "message": f"{column_name} values are within the contract valid_values list.",
                "evidence": {
                    "expected_values": valid_values,
                    "observed_values": [row["value"] for row in observed],
                },
                "affects": ["documentation"],
            }
        )

    return findings


def _check_column_checks(
    safe_table: str,
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for column_name, column_contract in contract_columns.items():
        if column_name not in actual_columns:
            continue

        checks = column_contract.get("checks", [])

        if not isinstance(checks, list):
            continue

        for check in checks:
            if not isinstance(check, dict):
                continue

            check_type = check.get("type")

            if check_type == "min_value":
                findings.extend(
                    _check_min_value(
                        safe_table=safe_table,
                        column_name=column_name,
                        check=check,
                        total_rows=total_rows,
                    )
                )

            if check_type == "max_column_value":
                findings.extend(
                    _check_max_column_value(
                        safe_table=safe_table,
                        column_name=column_name,
                        check=check,
                        actual_columns=actual_columns,
                        total_rows=total_rows,
                    )
                )

            if check_type == "required_when":
                findings.extend(
                    _check_required_when(
                        safe_table=safe_table,
                        column_name=column_name,
                        check=check,
                        actual_columns=actual_columns,
                        total_rows=total_rows,
                    )
                )

    return findings


def _check_min_value(
    safe_table: str,
    column_name: str,
    check: dict[str, Any],
    total_rows: int,
) -> list[dict[str, Any]]:
    safe_column = quote_identifier(column_name)
    min_value = check.get("value")
    inclusive = bool(check.get("inclusive", True))

    operator = "<" if inclusive else "<="

    row = fetch_one(
        f"""
        SELECT COUNT(*) AS invalid_count
        FROM {safe_table}
        WHERE {safe_column} IS NULL
           OR {safe_column} {operator} ?
        """,
        (min_value,),
    )

    invalid_count = int(row["invalid_count"]) if row else 0

    if invalid_count == 0:
        return []

    return [
        {
            "id": f"issue_{column_name}_below_min_value",
            "type": "numeric_constraint",
            "severity": check.get("severity", "must_answer"),
            "column": column_name,
            "message": (
                f"{column_name} is null or violates the minimum value rule "
                f"({column_name} {'>=' if inclusive else '>'} {min_value}) in {invalid_count} row(s)."
            ),
            "evidence": {
                "affected_rows": invalid_count,
                "total_rows": total_rows,
                "min_value": min_value,
                "inclusive": inclusive,
            },
            "affects": check.get("affects", _default_affects_for_column(column_name)),
        }
    ]


def _check_max_column_value(
    safe_table: str,
    column_name: str,
    check: dict[str, Any],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    compare_column = str(check.get("column", ""))

    if not compare_column or compare_column not in actual_columns:
        return []

    safe_column = quote_identifier(column_name)
    safe_compare_column = quote_identifier(compare_column)

    row = fetch_one(
        f"""
        SELECT COUNT(*) AS invalid_count
        FROM {safe_table}
        WHERE {safe_column} IS NOT NULL
          AND {safe_compare_column} IS NOT NULL
          AND {safe_column} > {safe_compare_column}
        """
    )

    invalid_count = int(row["invalid_count"]) if row else 0

    if invalid_count == 0:
        return []

    return [
        {
            "id": f"issue_{column_name}_greater_than_{compare_column}",
            "type": "cross_column_constraint",
            "severity": check.get("severity", "optional_review"),
            "column": column_name,
            "message": f"{column_name} is greater than {compare_column} in {invalid_count} row(s).",
            "evidence": {
                "affected_rows": invalid_count,
                "total_rows": total_rows,
                "compare_column": compare_column,
            },
            "affects": check.get("affects", ["data_tests", "documentation"]),
        }
    ]


def _check_required_when(
    safe_table: str,
    column_name: str,
    check: dict[str, Any],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    condition_column = str(check.get("column", ""))
    expected_value = check.get("equals")

    if not condition_column or condition_column not in actual_columns:
        return []

    safe_column = quote_identifier(column_name)
    safe_condition_column = quote_identifier(condition_column)

    row = fetch_one(
        f"""
        SELECT COUNT(*) AS missing_count
        FROM {safe_table}
        WHERE {safe_condition_column} = ?
          AND {safe_column} IS NULL
        """,
        (expected_value,),
    )

    missing_count = int(row["missing_count"]) if row else 0

    if missing_count == 0:
        return []

    return [
        {
            "id": f"issue_{column_name}_missing_when_{condition_column}_{expected_value}",
            "type": "conditional_required_value",
            "severity": check.get("severity", "must_answer"),
            "column": column_name,
            "message": (
                f"{missing_count} row(s) have {condition_column} = {expected_value} "
                f"but missing {column_name}."
            ),
            "evidence": {
                "affected_rows": missing_count,
                "total_rows": total_rows,
                "condition_column": condition_column,
                "condition_value": expected_value,
                "required_column": column_name,
            },
            "affects": check.get("affects", _default_affects_for_column(column_name)),
        }
    ]


def _check_business_rule_triggers(
    safe_table: str,
    contract: dict[str, Any],
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    findings.extend(
        _check_nullable_business_decisions(
            safe_table=safe_table,
            contract_columns=contract_columns,
            actual_columns=actual_columns,
            total_rows=total_rows,
        )
    )

    findings.extend(
        _check_refund_handling_needed(
            safe_table=safe_table,
            contract=contract,
            actual_columns=actual_columns,
            total_rows=total_rows,
        )
    )

    findings.extend(
        _check_multi_currency_needed(
            safe_table=safe_table,
            contract=contract,
            contract_columns=contract_columns,
            actual_columns=actual_columns,
            total_rows=total_rows,
        )
    )

    return findings


def _check_nullable_business_decisions(
    safe_table: str,
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for column_name, column_contract in contract_columns.items():
        if column_name not in actual_columns:
            continue

        business_rules = column_contract.get("business_rules")

        if not isinstance(business_rules, dict):
            continue

        threshold = business_rules.get("require_decision_when_null_rate_ge")

        if threshold is None:
            continue

        safe_column = quote_identifier(column_name)

        row = fetch_one(
            f"""
            SELECT COUNT(*) AS null_count
            FROM {safe_table}
            WHERE {safe_column} IS NULL
            """
        )

        null_count = int(row["null_count"]) if row else 0
        null_rate = null_count / total_rows

        if null_rate < float(threshold):
            continue

        findings.append(
            {
                "id": f"issue_{column_name}_null_rate",
                "type": "business_rule_needed",
                "severity": "must_answer",
                "column": column_name,
                "message": f"{column_name} is null in {null_rate:.1%} of rows.",
                "evidence": {
                    "null_count": null_count,
                    "total_rows": total_rows,
                    "null_rate": round(null_rate, 4),
                    "decision_threshold": threshold,
                    "decision_reason": business_rules.get("decision_reason"),
                },
                "affects": ["metric_logic", "sql_model", "documentation"],
            }
        )

    return findings


def _check_refund_handling_needed(
    safe_table: str,
    contract: dict[str, Any],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    business_rules = contract.get("business_rules", {})
    refund_rule = business_rules.get("refund_handling", {})

    if not isinstance(refund_rule, dict):
        return []

    status_value = refund_rule.get("required_when_status_present")

    if not status_value or "status" not in actual_columns:
        return []

    row = fetch_one(
        f"""
        SELECT COUNT(*) AS status_count
        FROM {safe_table}
        WHERE status = ?
        """,
        (status_value,),
    )

    status_count = int(row["status_count"]) if row else 0

    if status_count == 0:
        return []

    return [
        {
            "id": "issue_refund_handling_needed",
            "type": "business_rule_needed",
            "severity": refund_rule.get("severity", "must_answer"),
            "column": "status",
            "message": f"status contains {status_count} {status_value} payment row(s).",
            "evidence": {
                "status_value": status_value,
                "affected_rows": status_count,
                "total_rows": total_rows,
            },
            "affects": refund_rule.get("affects", ["metric_logic", "sql_model", "documentation"]),
        }
    ]


def _check_multi_currency_needed(
    safe_table: str,
    contract: dict[str, Any],
    contract_columns: dict[str, dict[str, Any]],
    actual_columns: dict[str, dict[str, Any]],
    total_rows: int,
) -> list[dict[str, Any]]:
    business_rules = contract.get("business_rules", {})
    currency_rule = business_rules.get("currency_handling", {})

    if not isinstance(currency_rule, dict):
        return []

    if not currency_rule.get("ask_when_multiple_valid_currencies", False):
        return []

    if "currency" not in actual_columns:
        return []

    valid_values = contract_columns.get("currency", {}).get("valid_values")

    if not isinstance(valid_values, list) or not valid_values:
        return []

    placeholders = ", ".join("?" for _ in valid_values)

    rows = fetch_all(
        f"""
        SELECT currency, COUNT(*) AS row_count
        FROM {safe_table}
        WHERE currency IS NOT NULL
          AND currency IN ({placeholders})
        GROUP BY currency
        ORDER BY row_count DESC
        """,
        tuple(valid_values),
    )

    values = [row["currency"] for row in rows]

    if len(values) <= 1:
        return []

    return [
        {
            "id": "issue_multi_currency",
            "type": "business_rule_needed",
            "severity": currency_rule.get("severity", "must_answer"),
            "column": "currency",
            "message": f"Source contains multiple valid currencies: {', '.join(values)}.",
            "evidence": {
                "currencies": rows,
                "total_rows": total_rows,
                "excluded_invalid_values": True,
            },
            "affects": currency_rule.get("affects", ["metric_logic", "sql_model", "documentation"]),
        }
    ]


def _normalize_contract_type(raw_type: str) -> str:
    value = raw_type.strip().lower()

    if value in {"string", "varchar", "text"}:
        return "text"

    if value in {"float", "double", "decimal", "numeric", "real"}:
        return "real"

    if value in {"int", "integer", "bigint"}:
        return "integer"

    return value


def _default_affects_for_column(column_name: str) -> list[str]:
    if column_name in {"amount", "currency", "status", "paid_at", "refunded_at", "discount_amount"}:
        return ["metric_logic", "sql_model", "data_tests"]

    if column_name in {"payment_id", "customer_id"}:
        return ["sql_model", "data_tests"]

    return ["data_tests", "documentation"]
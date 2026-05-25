from __future__ import annotations

import json
from typing import Any

from app.services.database.database_service import fetch_all, fetch_one, quote_identifier, table_exists


def validate_relationship(relationship: dict[str, Any]) -> dict[str, Any]:
    left_source = str(relationship["left_source"])
    right_source = str(relationship["right_source"])
    left_key = relationship["left_key"]
    right_key = relationship["right_key"]

    if isinstance(left_key, list) or isinstance(right_key, list):
        return _unsupported_aggregate_relationship_result(relationship)

    if not table_exists(left_source):
        raise RuntimeError(f"Relationship left source table does not exist: {left_source}")

    if not table_exists(right_source):
        raise RuntimeError(f"Relationship right source table does not exist: {right_source}")

    result = _validate_single_key_relationship(
        relationship=relationship,
        left_source=left_source,
        right_source=right_source,
        left_key=str(left_key),
        right_key=str(right_key),
    )

    result["relationship_profile_markdown"] = render_relationship_profile_markdown(result)
    result["join_quality_report_markdown"] = render_join_quality_report_markdown(result)
    result["relationship_context"] = build_relationship_context(result)

    return result


def validate_relationships(relationships: list[dict[str, Any]]) -> dict[str, Any]:
    results = {
        relationship["id"]: validate_relationship(relationship)
        for relationship in relationships
    }

    return {
        "relationships": results,
        "relationship_profile_markdown": render_all_relationship_profiles(results),
        "join_quality_report_markdown": render_all_join_quality_reports(results),
        "relationship_context": build_relationships_context(results),
        "findings": [
            finding
            for result in results.values()
            for finding in result.get("findings", [])
        ],
    }


def _validate_single_key_relationship(
    relationship: dict[str, Any],
    left_source: str,
    right_source: str,
    left_key: str,
    right_key: str,
) -> dict[str, Any]:
    safe_left = quote_identifier(left_source)
    safe_right = quote_identifier(right_source)
    safe_left_key = quote_identifier(left_key)
    safe_right_key = quote_identifier(right_key)

    left_count = _count_rows(left_source)
    right_count = _count_rows(right_source)

    left_key_missing = not _column_exists(left_source, left_key)
    right_key_missing = not _column_exists(right_source, right_key)

    findings: list[dict[str, Any]] = []

    if left_key_missing or right_key_missing:
        findings.append(
            {
                "id": f"{relationship['id']}__missing_join_key",
                "type": "missing_join_key",
                "severity": "must_answer",
                "message": (
                    f"Join key availability problem. "
                    f"left_key_missing={left_key_missing}, right_key_missing={right_key_missing}."
                ),
                "evidence": {
                    "left_source": left_source,
                    "left_key": left_key,
                    "right_source": right_source,
                    "right_key": right_key,
                },
                "affects": ["join_logic", "sql_model", "data_tests"],
            }
        )

        return {
            "relationship": relationship,
            "summary": {
                "left_rows": left_count,
                "right_rows": right_count,
                "status": "failed",
            },
            "findings": findings,
        }

    left_duplicate_count = _duplicate_key_count(left_source, left_key)
    right_duplicate_count = _duplicate_key_count(right_source, right_key)
    right_null_count = _null_key_count(right_source, right_key)

    unmatched_left_count = _unmatched_left_count(
        safe_left=safe_left,
        safe_right=safe_right,
        safe_left_key=safe_left_key,
        safe_right_key=safe_right_key,
    )
    unmatched_right_count = _unmatched_right_count(
        safe_left=safe_left,
        safe_right=safe_right,
        safe_left_key=safe_left_key,
        safe_right_key=safe_right_key,
    )

    left_unmatched_rate = unmatched_left_count / left_count if left_count else 0.0
    right_unmatched_rate = unmatched_right_count / right_count if right_count else 0.0
    right_null_rate = right_null_count / right_count if right_count else 0.0

    validation = relationship.get("validation", {})
    max_unmatched_left_rate = float(validation.get("max_unmatched_left_rate", 1.0))
    max_unmatched_right_rate = float(validation.get("max_unmatched_right_rate", 1.0))

    if left_duplicate_count > 0 and validation.get("left_key_unique"):
        findings.append(
            {
                "id": f"{relationship['id']}__left_key_duplicates",
                "type": "left_key_duplicates",
                "severity": "must_answer",
                "message": f"{left_duplicate_count} duplicate {left_source}.{left_key} value(s) were detected.",
                "evidence": {"duplicate_key_count": left_duplicate_count},
                "affects": ["join_logic", "sql_model", "data_tests"],
            }
        )

    if unmatched_left_count > 0:
        severity = "must_answer" if left_unmatched_rate > max_unmatched_left_rate else "optional_review"
        findings.append(
            {
                "id": _unmatched_left_issue_id(relationship, left_source, right_source),
                "type": "unmatched_left_records",
                "severity": severity,
                "message": f"{unmatched_left_count} {left_source} record(s) have no matching {right_source} record.",
                "evidence": {
                    "relationship_id": relationship["id"],
                    "left_source": left_source,
                    "right_source": right_source,
                    "left_key": left_key,
                    "right_key": right_key,
                    "unmatched_left_count": unmatched_left_count,
                    "unmatched_left_rate": round(left_unmatched_rate, 4),
                },
                "affects": ["join_logic", "metric_logic", "documentation"],
            }
        )

    if unmatched_right_count > 0 or right_null_count > 0:
        severity = "must_answer" if right_unmatched_rate > max_unmatched_right_rate else "optional_review"
        findings.append(
            {
                "id": _unmatched_right_issue_id(relationship, left_source, right_source),
                "type": "unmatched_right_records",
                "severity": severity,
                "message": (
                    f"{unmatched_right_count} {right_source} record(s) reference a missing {left_source} key "
                    f"and {right_null_count} have a null join key."
                ),
                "evidence": {
                    "relationship_id": relationship["id"],
                    "left_source": left_source,
                    "right_source": right_source,
                    "left_key": left_key,
                    "right_key": right_key,
                    "unmatched_right_count": unmatched_right_count,
                    "unmatched_right_rate": round(right_unmatched_rate, 4),
                    "right_null_count": right_null_count,
                    "right_null_rate": round(right_null_rate, 4),
                },
                "affects": ["join_logic", "metric_logic", "documentation"],
            }
        )

    payment_coverage = _relationship_specific_metrics(relationship, left_source, right_source, left_key, right_key)
    findings.extend(payment_coverage["findings"])

    status = "warning" if findings else "passed"

    return {
        "relationship": relationship,
        "summary": {
            "status": status,
            "left_source": left_source,
            "right_source": right_source,
            "left_key": left_key,
            "right_key": right_key,
            "left_rows": left_count,
            "right_rows": right_count,
            "left_duplicate_key_count": left_duplicate_count,
            "right_duplicate_key_count": right_duplicate_count,
            "right_null_key_count": right_null_count,
            "unmatched_left_count": unmatched_left_count,
            "unmatched_left_rate": round(left_unmatched_rate, 4),
            "unmatched_right_count": unmatched_right_count,
            "unmatched_right_rate": round(right_unmatched_rate, 4),
            **payment_coverage["summary"],
        },
        "findings": findings,
    }


def build_relationship_context(result: dict[str, Any]) -> str:
    compact = {
        "relationship": result.get("relationship"),
        "summary": result.get("summary"),
        "findings": result.get("findings", []),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def build_relationships_context(results: dict[str, dict[str, Any]]) -> str:
    compact = {
        relationship_id: {
            "relationship": result.get("relationship"),
            "summary": result.get("summary"),
            "findings": result.get("findings", []),
        }
        for relationship_id, result in results.items()
    }
    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def render_relationship_profile_markdown(result: dict[str, Any]) -> str:
    relationship = result["relationship"]
    summary = result.get("summary", {})

    lines = [
        f"# Relationship Profile: {relationship['id']}",
        "",
        relationship.get("business_meaning", ""),
        "",
        "## Join definition",
        "",
        f"- Left source: `{relationship.get('left_source')}`",
        f"- Right source: `{relationship.get('right_source')}`",
        f"- Left key: `{relationship.get('left_key')}`",
        f"- Right key: `{relationship.get('right_key')}`",
        f"- Relationship type: `{relationship.get('relationship_type')}`",
        f"- Recommended join type: `{relationship.get('recommended_join_type')}`",
        "",
        "## Validation summary",
        "",
    ]

    for key, value in summary.items():
        lines.append(f"- {key}: `{value}`")

    warnings = relationship.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines).strip() + "\n"


def render_join_quality_report_markdown(result: dict[str, Any]) -> str:
    relationship = result["relationship"]
    findings = result.get("findings", [])

    lines = [
        f"# Join Quality Report: {relationship['id']}",
        "",
    ]

    if not findings:
        lines.append("No relationship-level join quality findings were detected.")
        return "\n".join(lines).strip() + "\n"

    for finding in findings:
        lines.extend(
            [
                f"## {finding.get('id')}",
                "",
                f"- Type: `{finding.get('type')}`",
                f"- Severity: `{finding.get('severity')}`",
                f"- Message: {finding.get('message')}",
                f"- Affects: {', '.join(finding.get('affects', []))}",
                "",
                "Evidence:",
                "",
                "```json",
                json.dumps(finding.get("evidence", {}), ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def render_all_relationship_profiles(results: dict[str, dict[str, Any]]) -> str:
    return "\n\n".join(
        render_relationship_profile_markdown(result).strip()
        for result in results.values()
    ).strip() + "\n"


def render_all_join_quality_reports(results: dict[str, dict[str, Any]]) -> str:
    return "\n\n".join(
        render_join_quality_report_markdown(result).strip()
        for result in results.values()
    ).strip() + "\n"


def _unsupported_aggregate_relationship_result(relationship: dict[str, Any]) -> dict[str, Any]:
    result = {
        "relationship": relationship,
        "summary": {
            "status": "not_validated",
            "reason": "Composite/aggregate relationships are metadata-only in this MVP validator.",
        },
        "findings": [],
    }
    result["relationship_profile_markdown"] = render_relationship_profile_markdown(result)
    result["join_quality_report_markdown"] = render_join_quality_report_markdown(result)
    result["relationship_context"] = build_relationship_context(result)
    return result


def _relationship_specific_metrics(
    relationship: dict[str, Any],
    left_source: str,
    right_source: str,
    left_key: str,
    right_key: str,
) -> dict[str, Any]:
    if (
        left_source == "stripe_invoices"
        and right_source == "stripe_payments"
        and left_key == "invoice_id"
        and right_key == "invoice_id"
    ):
        payment_coverage = _invoice_payment_coverage()
        findings: list[dict[str, Any]] = []

        partial_count = payment_coverage["partial_count"]
        overpaid_count = payment_coverage["overpaid_count"]
        fully_paid_count = payment_coverage["fully_paid_count"]
        currency_mismatch_count = payment_coverage["currency_mismatch_count"]

        if partial_count > 0 or overpaid_count > 0:
            findings.append(
                {
                    "id": "issue_partial_or_overpaid_invoices",
                    "type": "payment_coverage_anomaly",
                    "severity": "must_answer",
                    "message": (
                        f"{partial_count} invoice(s) appear partially paid and "
                        f"{overpaid_count} invoice(s) appear overpaid after aggregating payments by invoice_id."
                    ),
                    "evidence": {
                        "partial_count": partial_count,
                        "overpaid_count": overpaid_count,
                        "fully_paid_count": fully_paid_count,
                    },
                    "affects": ["metric_logic", "sql_model", "documentation"],
                }
            )

        if currency_mismatch_count > 0:
            findings.append(
                {
                    "id": "issue_invoice_payment_currency_mismatch",
                    "type": "currency_mismatch",
                    "severity": "must_answer",
                    "message": f"{currency_mismatch_count} joined invoice/payment row(s) have mismatched currencies.",
                    "evidence": {"currency_mismatch_count": currency_mismatch_count},
                    "affects": ["join_logic", "metric_logic", "sql_model"],
                }
            )

        return {
            "summary": {
                "partial_count": partial_count,
                "overpaid_count": overpaid_count,
                "fully_paid_count": fully_paid_count,
                "currency_mismatch_count": currency_mismatch_count,
            },
            "findings": findings,
        }

    return {"summary": {}, "findings": []}


def _unmatched_left_issue_id(
    relationship: dict[str, Any],
    left_source: str,
    right_source: str,
) -> str:
    if relationship.get("id") == "invoices_to_payments_by_invoice_id":
        return "issue_unmatched_invoices"

    return f"issue_{left_source}_without_{right_source}"


def _unmatched_right_issue_id(
    relationship: dict[str, Any],
    left_source: str,
    right_source: str,
) -> str:
    if relationship.get("id") == "invoices_to_payments_by_invoice_id":
        return "issue_unmatched_payments"

    return f"issue_{right_source}_without_{left_source}"


def _count_rows(table_name: str) -> int:
    safe_table = quote_identifier(table_name)
    row = fetch_one(f"SELECT COUNT(*) AS count FROM {safe_table}")
    return int(row["count"]) if row else 0


def _column_exists(table_name: str, column_name: str) -> bool:
    safe_table = quote_identifier(table_name)
    rows = fetch_all(f"PRAGMA table_info({safe_table})")
    return any(row["name"] == column_name for row in rows)


def _duplicate_key_count(table_name: str, key: str) -> int:
    safe_table = quote_identifier(table_name)
    safe_key = quote_identifier(key)
    row = fetch_one(
        f"""
        SELECT COUNT(*) AS count
        FROM (
            SELECT {safe_key}
            FROM {safe_table}
            WHERE {safe_key} IS NOT NULL
            GROUP BY {safe_key}
            HAVING COUNT(*) > 1
        )
        """
    )
    return int(row["count"]) if row else 0


def _null_key_count(table_name: str, key: str) -> int:
    safe_table = quote_identifier(table_name)
    safe_key = quote_identifier(key)
    row = fetch_one(f"SELECT COUNT(*) AS count FROM {safe_table} WHERE {safe_key} IS NULL")
    return int(row["count"]) if row else 0


def _unmatched_left_count(
    safe_left: str,
    safe_right: str,
    safe_left_key: str,
    safe_right_key: str,
) -> int:
    row = fetch_one(
        f"""
        SELECT COUNT(*) AS count
        FROM {safe_left} AS l
        WHERE l.{safe_left_key} IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM {safe_right} AS r
            WHERE r.{safe_right_key} = l.{safe_left_key}
          )
        """
    )
    return int(row["count"]) if row else 0


def _unmatched_right_count(
    safe_left: str,
    safe_right: str,
    safe_left_key: str,
    safe_right_key: str,
) -> int:
    row = fetch_one(
        f"""
        SELECT COUNT(*) AS count
        FROM {safe_right} AS r
        WHERE r.{safe_right_key} IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM {safe_left} AS l
            WHERE l.{safe_left_key} = r.{safe_right_key}
          )
        """
    )
    return int(row["count"]) if row else 0


def _invoice_payment_coverage() -> dict[str, int]:
    rows = fetch_all(
        """
        WITH payments_by_invoice AS (
            SELECT
                invoice_id,
                currency,
                SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS collected_payment_amount,
                COUNT(*) AS payment_count
            FROM stripe_payments
            WHERE invoice_id IS NOT NULL
            GROUP BY invoice_id, currency
        ),
        invoice_coverage AS (
            SELECT
                i.invoice_id,
                i.invoice_amount,
                i.currency AS invoice_currency,
                COALESCE(SUM(p.collected_payment_amount), 0) AS collected_payment_amount,
                COALESCE(SUM(p.payment_count), 0) AS payment_count
            FROM stripe_invoices AS i
            LEFT JOIN payments_by_invoice AS p
              ON p.invoice_id = i.invoice_id
            WHERE i.invoice_amount > 0
            GROUP BY i.invoice_id, i.invoice_amount, i.currency
        )
        SELECT
            SUM(
              CASE
                WHEN payment_count > 0
                 AND collected_payment_amount > 0
                 AND collected_payment_amount < invoice_amount
                THEN 1 ELSE 0
              END
            ) AS partial_count,
            SUM(
              CASE
                WHEN payment_count > 0
                 AND collected_payment_amount > invoice_amount
                THEN 1 ELSE 0
              END
            ) AS overpaid_count,
            SUM(
              CASE
                WHEN payment_count > 0
                 AND collected_payment_amount = invoice_amount
                THEN 1 ELSE 0
              END
            ) AS fully_paid_count
        FROM invoice_coverage
        """
    )

    currency_row = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM stripe_invoices AS i
        JOIN stripe_payments AS p
          ON p.invoice_id = i.invoice_id
        WHERE p.invoice_id IS NOT NULL
          AND i.currency IS NOT NULL
          AND p.currency IS NOT NULL
          AND i.currency != p.currency
        """
    )

    row = rows[0] if rows else {}

    return {
        "partial_count": int(row.get("partial_count") or 0),
        "overpaid_count": int(row.get("overpaid_count") or 0),
        "fully_paid_count": int(row.get("fully_paid_count") or 0),
        "currency_mismatch_count": int(currency_row["count"]) if currency_row else 0,
    }

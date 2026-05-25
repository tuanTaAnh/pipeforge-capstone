from __future__ import annotations

import copy
import json
from typing import Any


def build_join_plan(
    data_product_contract: dict[str, Any],
    relationship_results: dict[str, Any],
) -> dict[str, Any]:
    data_product = data_product_contract["data_product"]
    artifact_plan = data_product["artifact_plan"]

    configured_join_plan = copy.deepcopy(data_product.get("join_plan", {}))
    configured_steps = configured_join_plan.get("steps")

    if isinstance(configured_steps, list) and configured_steps:
        steps = configured_steps
    else:
        steps = _default_join_plan_steps(data_product)

    return {
        "name": data_product["name"],
        "package_name": data_product.get("package_name"),
        "description": data_product.get("description"),
        "base_source": data_product.get("primary_source"),
        "sources": data_product.get("sources", []),
        "relationships": data_product.get("relationships", []),
        "grain": data_product.get("grain", []),
        "metrics": data_product.get("metrics", []),
        "artifact_plan": artifact_plan,
        "steps": steps,
        "relationship_validation_summary": {
            relationship_id: result.get("summary", {})
            for relationship_id, result in relationship_results.items()
        },
        "critical_rules": _critical_rules(data_product),
    }


def build_join_plan_context(join_plan: dict[str, Any]) -> str:
    return (
        "# Join Plan JSON\n\n"
        "Use this join plan as the source of truth for multi-table SQL generation.\n\n"
        "```json\n"
        + json.dumps(join_plan, ensure_ascii=False, indent=2, default=str)
        + "\n```"
    )


def render_join_plan_markdown(join_plan: dict[str, Any]) -> str:
    lines = [
        f"# Join Plan: {join_plan['name']}",
        "",
        str(join_plan.get("description", "")).strip(),
        "",
        "## Grain",
        "",
    ]

    for item in join_plan.get("grain", []):
        lines.append(f"- `{item}`")

    lines.extend(["", "## Sources", ""])

    for source in join_plan.get("sources", []):
        lines.append(f"- `{source}`")

    lines.extend(["", "## Relationships", ""])

    for relationship in join_plan.get("relationships", []):
        lines.append(f"- `{relationship}`")

    lines.extend(["", "## Steps", ""])

    for step in join_plan.get("steps", []):
        lines.extend(
            [
                f"### {step['id']}",
                "",
                f"- Type: `{step.get('type')}`",
                f"- Output model: `{step.get('output_model', 'n/a')}`",
                f"- Description: {step.get('description', '')}",
                "",
            ]
        )

        if step.get("relationship_id"):
            lines.append(f"- Relationship: `{step['relationship_id']}`")
        if step.get("source"):
            lines.append(f"- Source: `{step['source']}`")
        if step.get("input"):
            lines.append(f"- Input: `{step['input']}`")
        if step.get("base"):
            lines.append(f"- Base: `{step['base']}`")

        if step.get("group_by"):
            lines.extend(["", "Group by:"])
            for group_item in step["group_by"]:
                lines.append(f"- `{group_item}`")

        if step.get("joins"):
            lines.extend(["", "Joins:"])
            for join in step["joins"]:
                relationship_id = join.get("relationship_id", "unknown")
                left = join.get("left", "unknown")
                right = join.get("right", "unknown")
                lines.append(f"- `{relationship_id}`: `{left}` ↔ `{right}`")

        lines.append("")

    lines.extend(["## Critical rules", ""])

    for rule in join_plan.get("critical_rules", []):
        lines.append(f"- {rule}")

    return "\n".join(lines).strip() + "\n"


def _default_join_plan_steps(data_product: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback for older data products that do not define join_plan.steps."""
    name = data_product.get("name")

    if name == "stripe_billing_reconciliation":
        return [
            {
                "id": "stg_invoices",
                "type": "staging",
                "source": "stripe_invoices",
                "output_model": "stg_stripe__invoices",
                "description": "Clean and normalize invoice-level source records.",
            },
            {
                "id": "stg_payments",
                "type": "staging",
                "source": "stripe_payments",
                "output_model": "stg_stripe__payments",
                "description": "Clean and normalize payment-level source records, including invoice_id.",
            },
            {
                "id": "payments_by_invoice",
                "type": "aggregate",
                "input": "stg_stripe__payments",
                "group_by": ["invoice_id"],
                "metrics": [
                    {
                        "name": "collected_payment_amount",
                        "expression": "sum(successful_amount)",
                    },
                    {
                        "name": "payment_count",
                        "expression": "count(*)",
                    },
                ],
                "description": "Aggregate payments to invoice_id before joining to invoices.",
            },
            {
                "id": "invoice_payment_reconciliation",
                "type": "left_join",
                "relationship_id": "invoices_to_payments_by_invoice_id",
                "left": "stg_stripe__invoices",
                "right": "payments_by_invoice",
                "on": [
                    {"left": "invoice_id", "right": "invoice_id"},
                ],
                "output_model": "int_billing__invoice_payment_reconciliation",
                "description": (
                    "Left join invoices to aggregated payments. Preserve unmatched invoices and "
                    "calculate collected_successful_amount, reconciliation_difference, and payment coverage summary."
                ),
            },
            {
                "id": "monthly_reconciliation",
                "type": "aggregate",
                "input": "int_billing__invoice_payment_reconciliation",
                "group_by": ["invoice_month", "customer_segment"],
                "metrics": [
                    "sum(billed_amount) as billed_amount",
                    "sum(collected_payment_amount) as collected_payment_amount",
                    "sum(reconciliation_difference) as reconciliation_difference",
                    "count(*) as invoice_count",
                ],
                "output_model": "mart_billing__monthly_reconciliation",
                "description": "Create the monthly billing reconciliation mart.",
            },
        ]

    return [
        {
            "id": "multi_source_model",
            "type": "multi_join",
            "sources": data_product.get("sources", []),
            "relationships": data_product.get("relationships", []),
            "output_model": data_product.get("artifact_plan", {}).get("intermediate_model"),
            "description": "Build the configured multi-source intermediate model from data product metadata.",
        },
        {
            "id": "final_mart",
            "type": "aggregate",
            "input": data_product.get("artifact_plan", {}).get("intermediate_model"),
            "output_model": data_product.get("artifact_plan", {}).get("final_mart_name"),
            "description": "Build the configured final mart.",
        },
    ]


def _critical_rules(data_product: dict[str, Any]) -> list[str]:
    base_rules = [
        "Use the provided join_plan.steps as the source of truth.",
        "Do not invent additional sources or joins.",
        "Apply relationship validation findings and resolved business rules.",
        "Pre-aggregate many-side facts before joining when the join plan requires it.",
        "Preserve the configured final mart grain and metric definitions.",
    ]

    if "stripe_payments" in data_product.get("sources", []) and "stripe_invoices" in data_product.get("sources", []):
        base_rules.append(
            "Do not join raw invoices directly to raw payments by customer_id only; prefer invoice_id reconciliation or pre-aggregated customer/month joins."
        )

    return base_rules

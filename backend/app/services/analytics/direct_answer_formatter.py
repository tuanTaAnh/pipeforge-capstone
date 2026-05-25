from __future__ import annotations

import json
from typing import Any


def format_direct_answer(
    prompt: str,
    semantic_plan: dict[str, Any],
    sql_plan: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    metric_name = semantic_plan.get("metric_name")
    dimension_name = semantic_plan.get("dimension_name")
    intent = semantic_plan.get("intent")
    date_range = sql_plan.get("date_range", {})
    assumptions = sql_plan.get("assumptions", [])
    warnings = sql_plan.get("warnings", [])

    lines = ["# Direct Analytics Answer", "", f"**Question:** {prompt}", ""]

    lines.extend(["## Answer", ""])

    if not rows:
        lines.append("No matching rows were found for the resolved metric, time period, and filters.")
    elif intent == "top_k":
        first_row = rows[0]
        metric_value = first_row.get(metric_name)
        label = _best_label(first_row, dimension_name)
        lines.append(
            f"The top {dimension_name or 'group'} for **{metric_name}** is **{label}** "
            f"with **{_format_number(metric_value)}**."
        )
    elif len(rows) == 1:
        row = rows[0]
        metric_value = row.get(metric_name) or row.get("collection_rate")
        lines.append(f"The result is **{_format_number(metric_value)}**.")
    else:
        lines.append("The query returned multiple rows. Review the result table below.")

    lines.extend(["", "## Result rows", "", "```json", json.dumps(rows, ensure_ascii=False, indent=2, default=str), "```", ""])

    if date_range:
        lines.extend(
            [
                "## Time window",
                "",
                f"- Time phrase: `{date_range.get('time_phrase')}`",
                f"- Start date: `{date_range.get('start_date')}`",
                f"- End date exclusive: `{date_range.get('end_date')}`",
                f"- Anchor date: `{date_range.get('anchor_date')}`",
                "",
            ]
        )

    if assumptions:
        lines.extend(["## Assumptions", ""])
        for assumption in assumptions:
            lines.append(f"- {assumption}")
        lines.append("")

    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(["## SQL used", "", "```sql", sql_plan["sql"], "```", ""])

    return "\n".join(lines).strip() + "\n"


def format_chat_answer(
    semantic_plan: dict[str, Any],
    sql_plan: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    metric_name = semantic_plan.get("metric_name")
    dimension_name = semantic_plan.get("dimension_name")
    intent = semantic_plan.get("intent")
    date_range = sql_plan.get("date_range", {})

    if not rows:
        answer = "No matching rows were found for the resolved metric, time period, and filters."
    elif intent == "top_k":
        first_row = rows[0]
        metric_value = first_row.get(metric_name)
        label = _best_label(first_row, dimension_name)
        answer = (
            f"The top {dimension_name or 'group'} for {metric_name} is {label}, "
            f"with {_format_number(metric_value)}."
        )
    elif len(rows) == 1:
        row = rows[0]
        metric_value = row.get(metric_name) or row.get("collection_rate")
        answer = f"The result is {_format_number(metric_value)}."
    else:
        answer = f"The query returned {len(rows)} rows. See analytics_result.json for the table."

    time_text = ""
    if date_range.get("start_date") and date_range.get("end_date"):
        time_text = f"\nTime window: {date_range['start_date']} to {date_range['end_date']} (exclusive)."

    return (
        f"{answer}{time_text}\n\n"
        "I saved the SQL, result rows, semantic plan, and full explanation as reviewable artifacts."
    )


def _best_label(row: dict[str, Any], dimension_name: str | None) -> str:
    for key in ["customer_name", "plan_name", dimension_name or "", "customer_id", "plan_id", "result_group"]:
        if key and row.get(key) not in {None, ""}:
            return str(row[key])
    return json.dumps(row, ensure_ascii=False, default=str)


def _format_number(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    try:
        numeric = float(value)
        return f"{numeric:,.2f}"
    except (TypeError, ValueError):
        return str(value)

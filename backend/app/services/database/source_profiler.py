from __future__ import annotations

import json
from typing import Any

from app.data.seed_demo_db import ensure_demo_database
from app.services.metadata.contract_loader import (
    get_artifact_plan,
    get_contract_columns,
    load_source_contract,
)
from app.services.database.quality_checker import run_quality_checks
from app.services.database.schema_inspector import inspect_table_schema


def profile_source(table_name: str = "stripe_payments") -> dict[str, Any]:
    ensure_demo_database()

    contract = load_source_contract(table_name)
    schema = inspect_table_schema(table_name, contract=contract)
    findings = run_quality_checks(table_name, schema, contract)
    artifact_plan = get_artifact_plan(contract)

    profile = {
        "source": table_name,
        "dbt_source": schema["dbt_source"],
        "row_count": schema["row_count"],
        "contract": contract,
        "artifact_plan": artifact_plan,
        "columns": schema["columns"],
        "sample_rows": schema["sample_rows"],
        "quality_findings": findings,
    }

    profile["source_profile_markdown"] = render_source_profile_markdown(profile)
    profile["data_quality_report_markdown"] = render_data_quality_report_markdown(profile)
    profile["source_profile_context"] = build_source_profile_context(profile)

    return profile


def build_source_profile_context(profile: dict[str, Any]) -> str:
    contract_context = {
        "source": profile["contract"].get("source"),
        "business_context": profile["contract"].get("business_context"),
        "columns": profile["contract"].get("columns"),
        "business_rules": profile["contract"].get("business_rules"),
        "artifact_plan": profile.get("artifact_plan"),
    }

    return (
        profile["source_profile_markdown"]
        + "\n\n"
        + profile["data_quality_report_markdown"]
        + "\n\n"
        + "# Source Contract And Artifact Plan JSON\n\n"
        + "```json\n"
        + json.dumps(contract_context, ensure_ascii=False, indent=2, default=str)
        + "\n```"
    ).strip()


def render_source_profile_markdown(profile: dict[str, Any]) -> str:
    lines: list[str] = []

    contract = profile["contract"]
    artifact_plan = profile.get("artifact_plan", {})
    contract_columns = get_contract_columns(contract)

    lines.append(f"# Source Profile: {profile['source']}")
    lines.append("")
    lines.append(f"Rows: {profile['row_count']}")
    lines.append(f"dbt source: `{profile['dbt_source']}`")
    lines.append("")

    source_description = contract.get("source", {}).get("description")
    if source_description:
        lines.append(f"Description: {source_description}")
        lines.append("")

    lines.append("## Actual Columns")
    lines.append("")

    actual_column_names = {column["name"] for column in profile["columns"]}

    for column in profile["columns"]:
        column_name = column["name"]
        contract_column = contract_columns.get(column_name, {})
        expected_type = contract_column.get("type", "not defined")
        nullable = contract_column.get("nullable", "not defined")
        primary_key = contract_column.get("primary_key", False)

        notes = [
            f"actual type: {column['type']}",
            f"expected type: {expected_type}",
            f"nullable: {nullable}",
        ]

        if primary_key:
            notes.append("primary key: true")

        lines.append(f"- `{column_name}` ({'; '.join(notes)})")

    expected_only_columns = [
        column_name
        for column_name in contract_columns
        if column_name not in actual_column_names
    ]

    if expected_only_columns:
        lines.append("")
        lines.append("## Expected Columns Missing From Actual Source")
        lines.append("")

        for column_name in expected_only_columns:
            lines.append(f"- `{column_name}`")

    business_context = contract.get("business_context")

    if isinstance(business_context, dict):
        lines.append("")
        lines.append("## Business Context")
        lines.append("")

        if business_context.get("data_product_goal"):
            lines.append(f"- Goal: {business_context['data_product_goal']}")

        if business_context.get("final_mart"):
            lines.append(f"- Final mart: `{business_context['final_mart']}`")

        if business_context.get("metric_name"):
            lines.append(f"- Metric: `{business_context['metric_name']}`")

        grain = business_context.get("grain")
        if isinstance(grain, list):
            lines.append(f"- Grain: {', '.join(str(item) for item in grain)}")

    if artifact_plan:
        lines.append("")
        lines.append("## Artifact Plan")
        lines.append("")
        lines.append(f"- Package: {artifact_plan.get('package_name')}")
        lines.append(f"- Final mart: `{artifact_plan.get('final_mart_name')}`")

        model_files = artifact_plan.get("model_files", [])
        test_files = artifact_plan.get("test_files", [])
        documentation_files = artifact_plan.get("documentation_files", [])

        if model_files:
            lines.append(f"- Model files: {', '.join(str(item) for item in model_files)}")

        if test_files:
            lines.append(f"- Test files: {', '.join(str(item) for item in test_files)}")

        if documentation_files:
            lines.append(
                f"- Documentation files: {', '.join(str(item) for item in documentation_files)}"
            )

    info_findings = [
        finding
        for finding in profile["quality_findings"]
        if finding["severity"] == "info"
    ]

    if info_findings:
        lines.append("")
        lines.append("## Informational Findings")
        lines.append("")

        for finding in info_findings:
            lines.append(f"- {finding['message']}")

    return "\n".join(lines).strip() + "\n"


def render_data_quality_report_markdown(profile: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append(f"# Data Quality Report: {profile['source']}")
    lines.append("")
    lines.append(f"Rows profiled: {profile['row_count']}")
    lines.append("")
    lines.append("This report compares the live source table against the source contract.")
    lines.append("")

    must_answer = [
        finding
        for finding in profile["quality_findings"]
        if finding["severity"] == "must_answer"
    ]

    optional_review = [
        finding
        for finding in profile["quality_findings"]
        if finding["severity"] == "optional_review"
    ]

    info = [
        finding
        for finding in profile["quality_findings"]
        if finding["severity"] == "info"
    ]

    lines.append("## Business-Critical Findings")
    lines.append("")

    if must_answer:
        for finding in must_answer:
            lines.append(f"- **{finding['id']}**: {finding['message']}")
            lines.append(f"  - Type: {finding['type']}")
            lines.append(f"  - Column: {finding['column']}")
            lines.append(f"  - Affects: {', '.join(finding['affects'])}")
    else:
        lines.append("- No business-critical findings detected.")

    lines.append("")
    lines.append("## Engineering / Optional Review Findings")
    lines.append("")

    if optional_review:
        for finding in optional_review:
            lines.append(f"- **{finding['id']}**: {finding['message']}")
            lines.append(f"  - Type: {finding['type']}")
            lines.append(f"  - Column: {finding['column']}")
            lines.append(f"  - Affects: {', '.join(finding['affects'])}")
    else:
        lines.append("- No optional-review findings detected.")

    lines.append("")
    lines.append("## Informational Findings")
    lines.append("")

    if info:
        for finding in info:
            lines.append(f"- **{finding['id']}**: {finding['message']}")
    else:
        lines.append("- No informational findings detected.")

    return "\n".join(lines).strip() + "\n"
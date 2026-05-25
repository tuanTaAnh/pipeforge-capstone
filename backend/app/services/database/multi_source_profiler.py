from __future__ import annotations

import json
from typing import Any

from app.services.database.source_profiler import profile_source


def profile_sources(source_names: list[str]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}

    for source_name in source_names:
        profiles[source_name] = profile_source(source_name)

    combined_profile = {
        "sources": profiles,
        "source_names": source_names,
        "quality_findings": _combined_quality_findings(profiles),
    }

    combined_profile["source_profile_markdown"] = render_multi_source_profile_markdown(combined_profile)
    combined_profile["data_quality_report_markdown"] = render_multi_source_quality_report_markdown(combined_profile)
    combined_profile["source_profile_context"] = build_multi_source_profile_context(combined_profile)

    return combined_profile


def build_multi_source_profile_context(profile: dict[str, Any]) -> str:
    compact_sources: dict[str, Any] = {}

    for source_name, source_profile in profile.get("sources", {}).items():
        contract = source_profile.get("contract", {})
        compact_sources[source_name] = {
            "source": source_profile.get("source"),
            "dbt_source": source_profile.get("dbt_source"),
            "row_count": source_profile.get("row_count"),
            "artifact_plan": source_profile.get("artifact_plan"),
            "contract": {
                "source": contract.get("source"),
                "business_context": contract.get("business_context"),
                "columns": contract.get("columns"),
                "business_rules": contract.get("business_rules"),
            },
            "quality_findings": source_profile.get("quality_findings", []),
            "sample_rows": source_profile.get("sample_rows", []),
        }

    return (
        profile["source_profile_markdown"]
        + "\n\n"
        + profile["data_quality_report_markdown"]
        + "\n\n"
        + "# Multi-Source Profile JSON\n\n"
        + "```json\n"
        + json.dumps(compact_sources, ensure_ascii=False, indent=2, default=str)
        + "\n```"
    )


def render_multi_source_profile_markdown(profile: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Multi-Source Profile",
        "",
        "This profile summarizes every source selected for the multi-table data product.",
        "",
    ]

    for source_name, source_profile in profile.get("sources", {}).items():
        lines.extend(
            [
                f"## Source: `{source_name}`",
                "",
                f"- dbt source: `{source_profile.get('dbt_source')}`",
                f"- row count: {source_profile.get('row_count')}",
                "",
                "### Columns",
                "",
            ]
        )

        for column in source_profile.get("columns", []):
            lines.append(
                f"- `{column['name']}` ({column['normalized_type']})"
            )

        lines.extend(["", "### Sample rows", "", "```json"])
        lines.append(
            json.dumps(source_profile.get("sample_rows", []), indent=2, ensure_ascii=False, default=str)
        )
        lines.extend(["```", ""])

    return "\n".join(lines).strip() + "\n"


def render_multi_source_quality_report_markdown(profile: dict[str, Any]) -> str:
    lines: list[str] = [
        "# Multi-Source Data Quality Report",
        "",
    ]

    findings = profile.get("quality_findings", [])

    if not findings:
        lines.append("No deterministic data quality findings were detected across the selected sources.")
        return "\n".join(lines).strip() + "\n"

    for source_name, source_profile in profile.get("sources", {}).items():
        source_findings = source_profile.get("quality_findings", [])

        lines.extend(
            [
                f"## Source: `{source_name}`",
                "",
            ]
        )

        if not source_findings:
            lines.extend(["No findings detected for this source.", ""])
            continue

        for finding in source_findings:
            lines.extend(
                [
                    f"### {finding.get('id')}",
                    "",
                    f"- Severity: `{finding.get('severity')}`",
                    f"- Type: `{finding.get('type')}`",
                    f"- Column: `{finding.get('column')}`",
                    f"- Message: {finding.get('message')}",
                    f"- Affects: {', '.join(finding.get('affects', []))}",
                    "",
                    "Evidence:",
                    "",
                    "```json",
                    json.dumps(finding.get("evidence", {}), indent=2, ensure_ascii=False, default=str),
                    "```",
                    "",
                ]
            )

    return "\n".join(lines).strip() + "\n"


def _combined_quality_findings(profiles: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for source_name, profile in profiles.items():
        for finding in profile.get("quality_findings", []):
            enriched = {
                **finding,
                "source": source_name,
                "id": f"{source_name}__{finding.get('id')}",
            }
            findings.append(enriched)

    return findings

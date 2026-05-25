from __future__ import annotations

import re
from typing import Any


def build_resolved_rule(
    question: dict[str, Any],
    validation_result: dict[str, Any],
) -> dict[str, Any]:
    if not validation_result["is_valid"]:
        raise ValueError("Cannot build resolved rule from invalid answer.")

    return {
        "question_id": question["id"],
        "issue_id": question["issue_id"],
        "issue_summary": question["issue_summary"],
        "question": question["question"],
        "answer_type": validation_result["answer_type"],
        "raw_answer": validation_result["raw_answer"],
        "selected_option_id": validation_result.get("selected_option_id"),
        "decision": validation_result["resolved_rule"],
        "implementation": validation_result["implementation"],
        "source": validation_result["source"],
    }


def build_business_rules_yaml(resolved_rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    lines.append("version: 1")
    lines.append("rules:")

    if not resolved_rules:
        lines.append("  {}")
        return "\n".join(lines).strip() + "\n"

    used_keys: set[str] = set()

    for rule in resolved_rules:
        key = _unique_rule_key(_question_id_to_rule_key(rule["question_id"]), used_keys)
        used_keys.add(key)

        lines.append(f"  {key}:")
        lines.append(f"    question_id: {_quote(rule['question_id'])}")
        lines.append(f"    issue_id: {_quote(rule['issue_id'])}")
        lines.append(f"    issue: {_quote(rule['issue_summary'])}")
        lines.append(f"    question: {_quote(rule['question'])}")
        lines.append(f"    decision: {_quote(rule['decision'])}")
        lines.append(f"    implementation: {_quote(rule['implementation'])}")
        lines.append(f"    answer_type: {_quote(rule['answer_type'])}")
        lines.append(f"    source: {_quote(rule['source'])}")

    return "\n".join(lines).strip() + "\n"


def build_business_rules_markdown(resolved_rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    lines.append("# Resolved Business Rules")
    lines.append("")

    if not resolved_rules:
        lines.append("No business rules were resolved.")
        return "\n".join(lines).strip() + "\n"

    for rule in resolved_rules:
        lines.append(f"## {rule['question_id']}")
        lines.append("")
        lines.append(f"Detected issue: {rule['issue_summary']}")
        lines.append("")
        lines.append(f"Question: {rule['question']}")
        lines.append("")
        lines.append(f"Decision: {rule['decision']}")
        lines.append("")
        lines.append(f"Implementation: `{rule['implementation']}`")
        lines.append("")
        lines.append(f"Source: {rule['source']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _question_id_to_rule_key(question_id: str) -> str:
    cleaned = question_id

    if cleaned.startswith("q_"):
        cleaned = cleaned[2:]

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_").lower()

    return cleaned or "business_rule"


def _unique_rule_key(base_key: str, used_keys: set[str]) -> str:
    if base_key not in used_keys:
        return base_key

    index = 2

    while f"{base_key}_{index}" in used_keys:
        index += 1

    return f"{base_key}_{index}"


def _quote(value: Any) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
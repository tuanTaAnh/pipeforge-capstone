from __future__ import annotations

import re
from typing import Any


def build_resolved_rule(
    question: dict[str, Any],
    validation_result: dict[str, Any],
) -> dict[str, Any]:
    if not validation_result["is_valid"]:
        raise ValueError("Cannot build resolved rule from invalid answer.")

    question_id = _resolve_question_id(question, validation_result)
    issue_id = _resolve_issue_id(question, validation_result, question_id)

    return {
        "question_id": question_id,
        "issue_id": issue_id,
        "issue_summary": _resolve_issue_summary(question),
        "question": str(question.get("question") or "Business decision question."),
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
        question_id = str(rule.get("question_id") or "business_rule")
        issue_id = str(rule.get("issue_id") or question_id)

        key = _unique_rule_key(_question_id_to_rule_key(question_id), used_keys)
        used_keys.add(key)

        lines.append(f"  {key}:")
        lines.append(f"    question_id: {_quote(question_id)}")
        lines.append(f"    issue_id: {_quote(issue_id)}")
        lines.append(f"    issue: {_quote(rule.get('issue_summary') or '')}")
        lines.append(f"    question: {_quote(rule.get('question') or '')}")
        lines.append(f"    decision: {_quote(rule.get('decision') or '')}")
        lines.append(f"    implementation: {_quote(rule.get('implementation') or '')}")
        lines.append(f"    answer_type: {_quote(rule.get('answer_type') or '')}")
        lines.append(f"    source: {_quote(rule.get('source') or '')}")

    return "\n".join(lines).strip() + "\n"


def build_business_rules_markdown(resolved_rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    lines.append("# Resolved Business Rules")
    lines.append("")

    if not resolved_rules:
        lines.append("No business rules were resolved.")
        return "\n".join(lines).strip() + "\n"

    for rule in resolved_rules:
        question_id = str(rule.get("question_id") or "business_rule")
        issue_summary = str(rule.get("issue_summary") or "No issue summary provided.")
        question = str(rule.get("question") or "Business decision question.")
        decision = str(rule.get("decision") or "")
        implementation = str(rule.get("implementation") or "")
        source = str(rule.get("source") or "")

        lines.append(f"## {question_id}")
        lines.append("")
        lines.append(f"Detected issue: {issue_summary}")
        lines.append("")
        lines.append(f"Question: {question}")
        lines.append("")
        lines.append(f"Decision: {decision}")
        lines.append("")
        lines.append(f"Implementation: `{implementation}`")
        lines.append("")
        lines.append(f"Source: {source}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _resolve_question_id(question: dict[str, Any], validation_result: dict[str, Any]) -> str:
    return str(
        question.get("id")
        or question.get("question_id")
        or question.get("questionId")
        or validation_result.get("question_id")
        or validation_result.get("questionId")
        or "business_rule"
    )


def _resolve_issue_id(
    question: dict[str, Any],
    validation_result: dict[str, Any],
    question_id: str,
) -> str:
    return str(
        question.get("issue_id")
        or question.get("issueId")
        or validation_result.get("issue_id")
        or validation_result.get("issueId")
        or question_id
    )


def _resolve_issue_summary(question: dict[str, Any]) -> str:
    return str(
        question.get("issue_summary")
        or question.get("issueSummary")
        or question.get("question")
        or "Business decision collected from the user."
    )


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

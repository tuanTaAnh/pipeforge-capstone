from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.services.llm_client import llm_client


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

USE_LLM_QUESTION_PLANNER = os.getenv("USE_LLM_QUESTION_PLANNER", "1") == "1"
QUESTION_PLANNER_MAX_MUST_ANSWER = int(os.getenv("QUESTION_PLANNER_MAX_MUST_ANSWER", "3"))

_SAFE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class PlannedOption(BaseModel):
    id: str
    label: str
    resolved_rule: str
    implementation: str


class PlannedQuestion(BaseModel):
    id: str
    issue_id: str
    priority: Literal["must_answer", "optional_review"] = "must_answer"
    issue_summary: str
    question: str
    recommended_option_id: str
    recommendation_reason: str
    options: list[PlannedOption] = Field(min_length=2, max_length=4)
    allow_custom_answer: bool = True

    @model_validator(mode="after")
    def validate_question(self) -> "PlannedQuestion":
        if not self.id.startswith("q_"):
            raise ValueError("question id must start with q_")

        if not _SAFE_ID_PATTERN.match(self.id):
            raise ValueError(f"unsafe question id: {self.id}")

        option_ids = [option.id for option in self.options]

        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"duplicate option ids in question {self.id}")

        for option_id in option_ids:
            if not _SAFE_ID_PATTERN.match(option_id):
                raise ValueError(f"unsafe option id: {option_id}")

        if self.recommended_option_id not in option_ids:
            raise ValueError(
                f"recommended_option_id={self.recommended_option_id} does not match any option id"
            )

        return self


class QuestionPlan(BaseModel):
    questions: list[PlannedQuestion] = Field(default_factory=list)


async def plan_questions(
    profile: dict[str, Any],
    user_request: str | None = None,
) -> list[dict[str, Any]]:
    fallback_questions = build_fallback_questions(profile)

    if not USE_LLM_QUESTION_PLANNER:
        return fallback_questions

    try:
        llm_questions = await _plan_questions_with_llm(profile, user_request)

        if not llm_questions:
            print(
                "[PF WARNING][question_planner] LLM returned no valid questions. Falling back to deterministic templates.",
                flush=True,
            )
            return fallback_questions

        return llm_questions

    except Exception as exc:
        print(
            f"[PF WARNING][question_planner] LLM question planning failed: {exc}. Falling back to deterministic templates.",
            flush=True,
        )
        return fallback_questions


async def _plan_questions_with_llm(
    profile: dict[str, Any],
    user_request: str | None,
) -> list[dict[str, Any]]:
    system_prompt = _load_prompt("question_planner_prompt.txt").replace(
        "{{MAX_MUST_ANSWER_QUESTIONS}}",
        str(QUESTION_PLANNER_MAX_MUST_ANSWER),
    )

    user_prompt = _build_user_prompt(profile, user_request)

    response_json = await llm_client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=3500,
    )

    plan = QuestionPlan.model_validate(response_json)

    issue_ids = {
        finding["id"]
        for finding in profile.get("quality_findings", [])
        if isinstance(finding, dict) and "id" in finding
    }

    validated_questions = []

    for question in plan.questions:
        question_dict = question.model_dump()

        if question_dict["issue_id"] not in issue_ids:
            print(
                f"[PF WARNING][question_planner] Dropping question with unknown issue_id={question_dict['issue_id']}",
                flush=True,
            )
            continue

        validated_questions.append(question_dict)

    return _select_questions(validated_questions)


def _build_user_prompt(profile: dict[str, Any], user_request: str | None) -> str:
    contract = profile.get("contract", {})

    compact_profile = {
        "user_request": user_request,
        "source": profile.get("source"),
        "dbt_source": profile.get("dbt_source"),
        "row_count": profile.get("row_count"),
        "contract": {
            "source": contract.get("source"),
            "business_context": contract.get("business_context"),
            "columns": contract.get("columns"),
            "business_rules": contract.get("business_rules"),
        },
        "actual_columns": profile.get("columns", []),
        "quality_findings": [
            {
                "id": finding.get("id"),
                "type": finding.get("type"),
                "severity": finding.get("severity"),
                "column": finding.get("column"),
                "message": finding.get("message"),
                "evidence": finding.get("evidence"),
                "affects": finding.get("affects"),
            }
            for finding in profile.get("quality_findings", [])
            if isinstance(finding, dict)
        ],
    }

    return "\n".join(
        [
            "User request:",
            user_request or "No user request provided.",
            "",
            "Current contract-aware source profile and data quality findings as JSON:",
            json.dumps(compact_profile, ensure_ascii=False, indent=2, default=str),
            "",
            "Create the question plan now.",
        ]
    )


def _select_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    must_answer = [
        question
        for question in questions
        if question.get("priority") == "must_answer"
    ]

    optional_review = [
        question
        for question in questions
        if question.get("priority") == "optional_review"
    ]

    selected = must_answer[:QUESTION_PLANNER_MAX_MUST_ANSWER]

    if selected:
        return selected

    return optional_review[:1]


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename

    if not path.exists():
        raise RuntimeError(f"Prompt file not found: {path}")

    return path.read_text(encoding="utf-8")


def build_fallback_questions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    findings = profile["quality_findings"]
    questions: list[dict[str, Any]] = []

    by_id = {finding["id"]: finding for finding in findings}

    if "issue_discount_amount_null_rate" in by_id:
        questions.append(_missing_discount_question(by_id["issue_discount_amount_null_rate"]))

    if "issue_refund_handling_needed" in by_id:
        questions.append(_refund_handling_question(by_id["issue_refund_handling_needed"]))

    if "issue_multi_currency" in by_id:
        questions.append(_currency_handling_question(by_id["issue_multi_currency"]))

    if "issue_payment_id_duplicates" in by_id:
        questions.append(_duplicate_payment_id_question(by_id["issue_payment_id_duplicates"]))

    if "issue_status_invalid_values" in by_id:
        questions.append(_invalid_status_question(by_id["issue_status_invalid_values"]))

    if "issue_payment_id_duplicates" not in by_id and "issue_payment_id_duplicates" in {
        _normalize_duplicate_issue_id(finding_id)
        for finding_id in by_id
    }:
        duplicate_issue = _find_issue_by_suffix(by_id, "_duplicates")
        if duplicate_issue:
            questions.append(_duplicate_payment_id_question(duplicate_issue))

    return _select_questions(questions)


def _normalize_duplicate_issue_id(issue_id: str) -> str:
    if issue_id == "issue_payment_id_duplicates":
        return issue_id

    if issue_id.endswith("_duplicates") and "payment_id" in issue_id:
        return "issue_payment_id_duplicates"

    return issue_id


def _find_issue_by_suffix(
    findings_by_id: dict[str, dict[str, Any]],
    suffix: str,
) -> dict[str, Any] | None:
    for issue_id, finding in findings_by_id.items():
        if issue_id.endswith(suffix):
            return finding

    return None


def _missing_discount_question(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "q_missing_discount_handling",
        "issue_id": issue["id"],
        "priority": "must_answer",
        "issue_summary": issue["message"],
        "question": "How should missing discount_amount values be handled?",
        "recommended_option_id": "treat_as_zero",
        "recommendation_reason": "In payment data, a missing discount commonly means no discount was applied.",
        "options": [
            {
                "id": "treat_as_zero",
                "label": "Treat missing discount as 0",
                "resolved_rule": "Treat missing discount_amount as 0 using coalesce(discount_amount, 0).",
                "implementation": "coalesce(discount_amount, 0)",
            },
            {
                "id": "exclude_missing",
                "label": "Exclude rows with missing discount",
                "resolved_rule": "Exclude rows where discount_amount is null before revenue aggregation.",
                "implementation": "discount_amount is not null",
            },
            {
                "id": "flag_for_review",
                "label": "Keep rows but flag missing discounts for review",
                "resolved_rule": "Keep rows and add a has_missing_discount flag for review.",
                "implementation": "discount_amount is null as has_missing_discount",
            },
        ],
        "allow_custom_answer": True,
    }


def _refund_handling_question(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "q_refund_handling",
        "issue_id": issue["id"],
        "priority": "must_answer",
        "issue_summary": issue["message"],
        "question": "How should refunded payments affect monthly recurring revenue?",
        "recommended_option_id": "subtract_refunds",
        "recommendation_reason": "For board-level revenue reporting, refunds usually reduce net revenue.",
        "options": [
            {
                "id": "subtract_refunds",
                "label": "Subtract refunds from revenue",
                "resolved_rule": "Refunded payments should reduce net revenue.",
                "implementation": "case when status = 'refunded' then -net_amount",
            },
            {
                "id": "exclude_refunds",
                "label": "Exclude refunded payments from MRR",
                "resolved_rule": "Refunded payments should be excluded from MRR calculations.",
                "implementation": "status != 'refunded'",
            },
            {
                "id": "separate_refund_metric",
                "label": "Track refunds as a separate metric",
                "resolved_rule": "Refunds should be tracked as a separate refund_amount metric.",
                "implementation": "separate refund_amount and gross_revenue_amount",
            },
        ],
        "allow_custom_answer": True,
    }


def _currency_handling_question(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "q_currency_handling",
        "issue_id": issue["id"],
        "priority": "must_answer",
        "issue_summary": issue["message"],
        "question": "How should revenue be reported across multiple currencies?",
        "recommended_option_id": "group_by_currency",
        "recommendation_reason": "Without FX rates, summing multiple currencies into one number would be misleading.",
        "options": [
            {
                "id": "group_by_currency",
                "label": "Group revenue by currency",
                "resolved_rule": "Revenue should be aggregated separately by currency.",
                "implementation": "group by revenue_month, customer_segment, currency",
            },
            {
                "id": "convert_to_reporting_currency",
                "label": "Convert all revenue to one reporting currency",
                "resolved_rule": "Revenue should be converted to a single reporting currency before aggregation.",
                "implementation": "join FX rates and convert amount before aggregation",
            },
            {
                "id": "separate_currency_marts",
                "label": "Generate separate marts per currency",
                "resolved_rule": "Generate separate revenue marts per currency.",
                "implementation": "filter or partition marts by currency",
            },
        ],
        "allow_custom_answer": True,
    }


def _duplicate_payment_id_question(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "q_duplicate_payment_id_handling",
        "issue_id": issue["id"],
        "priority": "must_answer",
        "issue_summary": issue["message"],
        "question": "How should duplicate payment_id records be handled?",
        "recommended_option_id": "deduplicate_payment_id",
        "recommendation_reason": "Duplicate payment identifiers can double-count revenue if not handled.",
        "options": [
            {
                "id": "deduplicate_payment_id",
                "label": "Deduplicate by payment_id",
                "resolved_rule": "Deduplicate records by payment_id before revenue aggregation.",
                "implementation": "row_number() over (partition by payment_id order by paid_at desc)",
            },
            {
                "id": "flag_duplicates",
                "label": "Keep rows but flag duplicate payment IDs",
                "resolved_rule": "Keep duplicate rows but flag them for downstream review.",
                "implementation": "add is_duplicate_payment_id flag",
            },
            {
                "id": "stop_pipeline",
                "label": "Stop pipeline until duplicates are fixed upstream",
                "resolved_rule": "Do not generate production pipeline output until duplicate payment IDs are fixed upstream.",
                "implementation": "blocking data quality test",
            },
        ],
        "allow_custom_answer": True,
    }


def _invalid_status_question(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "q_invalid_status_handling",
        "issue_id": issue["id"],
        "priority": "must_answer",
        "issue_summary": issue["message"],
        "question": "How should unexpected status values be handled?",
        "recommended_option_id": "exclude_invalid_status",
        "recommendation_reason": "Unexpected payment statuses should not affect trusted revenue metrics until reviewed.",
        "options": [
            {
                "id": "exclude_invalid_status",
                "label": "Exclude unexpected statuses from revenue",
                "resolved_rule": "Rows with unexpected status values should be excluded from revenue calculations.",
                "implementation": "status in ('paid', 'failed', 'refunded')",
            },
            {
                "id": "map_to_non_revenue",
                "label": "Map unexpected statuses to non-revenue",
                "resolved_rule": "Unexpected status values should be mapped to non-revenue.",
                "implementation": "else 0 as net_revenue_amount",
            },
            {
                "id": "flag_invalid_status",
                "label": "Keep rows but flag invalid statuses",
                "resolved_rule": "Keep rows with unexpected status values but flag them for review.",
                "implementation": "add has_invalid_status flag",
            },
        ],
        "allow_custom_answer": True,
    }
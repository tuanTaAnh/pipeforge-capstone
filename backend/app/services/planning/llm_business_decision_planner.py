from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from app.schemas.llm_plans import BusinessDecisionPlan, RequestPlan
from app.services.llm.llm_client import LLMResponseTextExtractionError, llm_client
from app.services.planning.metadata_context_builder import build_llm_metadata_prompt_context
from app.services.planning.planner_repair import repair_planner_json
from app.services.runtime.flow_logger import flow_log, log_step_failure, log_step_start, log_step_success, summarize_text
from app.utils.prompt_loader import load_prompt_text


MAX_COMPACT_FINDINGS = 12
MAX_COMPACT_PROFILE_CHARS = 9000


async def plan_business_decisions_with_llm(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    previous_user_answers: list[dict[str, Any]] | None = None,
    max_repair_attempts: int = 1,
    run_id: str | None = None,
) -> BusinessDecisionPlan:
    system_prompt = load_prompt_text("business_decision_planner_prompt.txt")
    compact_profiling_context = compact_profile_context_for_business_decisions(
        profiling_context=profiling_context,
        selected_sources=request_plan.selected_sources,
        previous_user_answers=previous_user_answers or [],
    )
    flow_log(
        run_id=run_id,
        step_id="7B",
        step_name="Prepare compact business-decision context",
        event="context_compacted",
        status="completed",
        details={
            "selected_sources": request_plan.selected_sources,
            "previous_answer_count": len(previous_user_answers or []),
            "raw_profile_chars": len(profiling_context),
            "compact_profile": summarize_text(compact_profiling_context, max_chars=1600),
        },
    )
    user_prompt = _build_user_prompt(
        user_question=user_question,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=compact_profiling_context,
        previous_user_answers=previous_user_answers or [],
    )

    try:
        raw = await llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=1200,
            run_id=run_id,
            step_id="7B",
            call_name="LLM Business Decision Planner",
        )
    except LLMResponseTextExtractionError as exc:
        # The most common failure mode for this planner is max_output_tokens spent on
        # reasoning after receiving too much profile context. The planner is advisory:
        # if we already have user decisions and compact warnings, we can safely proceed
        # with warnings instead of failing the entire data product generation run.
        fallback = _fallback_decision_plan(
            reason=f"Business decision planner did not return JSON: {exc}",
            previous_user_answers=previous_user_answers or [],
            compact_context=compact_profiling_context,
        )
        flow_log(run_id=run_id, step_id="7B", step_name="LLM Business Decision Planner", event="fallback", status="warning", details={"reason": str(exc), "fallback": fallback.model_dump()})
        return fallback
    except RuntimeError as exc:
        message = str(exc)
        if "max_output_tokens" in message or "Could not extract text" in message:
            fallback = _fallback_decision_plan(
                reason=f"Business decision planner could not produce JSON: {message}",
                previous_user_answers=previous_user_answers or [],
                compact_context=compact_profiling_context,
            )
            flow_log(run_id=run_id, step_id="7B", step_name="LLM Business Decision Planner", event="fallback", status="warning", details={"reason": message, "fallback": fallback.model_dump()})
            return fallback
        raise

    for attempt in range(max_repair_attempts + 1):
        validation_timer = log_step_start(run_id, "7B-validate", "Validate business decision plan", {"attempt": attempt + 1, "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else None})
        try:
            plan = BusinessDecisionPlan.model_validate(raw)
            _validate_questions(plan)
            normalized_plan = _normalize_decision_plan(plan)
            log_step_success(run_id, "7B-validate", "Validate business decision plan", started_at=validation_timer, details={"clarification_required": normalized_plan.clarification_required, "question_count": len(normalized_plan.questions), "assumptions": normalized_plan.assumptions, "warnings": normalized_plan.warnings})
            return normalized_plan
        except Exception as exc:
            errors = getattr(exc, "errors", None)
            validation_errors = [str(item) for item in errors()] if callable(errors) else [str(exc)]
            log_step_failure(run_id, "7B-validate", "Validate business decision plan", started_at=validation_timer, error=exc, details={"attempt": attempt + 1, "validation_errors": validation_errors})

            if attempt >= max_repair_attempts:
                fallback = _fallback_decision_plan(
                    reason="Business decision planner output failed validation: " + "; ".join(validation_errors[:3]),
                    previous_user_answers=previous_user_answers or [],
                    compact_context=compact_profiling_context,
                )
                flow_log(run_id=run_id, step_id="7B", step_name="LLM Business Decision Planner", event="fallback", status="warning", details={"validation_errors": validation_errors, "fallback": fallback.model_dump()})
                return fallback
            raw = await repair_planner_json(
                original_system_prompt=system_prompt,
                original_user_prompt=user_prompt,
                invalid_output=raw if isinstance(raw, dict) else {"raw": raw},
                validation_errors=validation_errors,
                max_output_tokens=1200,
                run_id=run_id,
                step_id="7B-repair",
            )

    fallback = _fallback_decision_plan(
        reason="Business decision planner failed unexpectedly.",
        previous_user_answers=previous_user_answers or [],
        compact_context=compact_profiling_context,
    )
    flow_log(run_id=run_id, step_id="7B", step_name="LLM Business Decision Planner", event="fallback", status="warning", details={"fallback": fallback.model_dump()})
    return fallback


def compact_profile_context_for_business_decisions(
    *,
    profiling_context: str,
    selected_sources: list[str],
    previous_user_answers: list[dict[str, Any]],
) -> str:
    """Build a compact decision-focused profile summary for the LLM.

    The full source/relationship profile can be very large and is already saved as
    artifacts. This planner only needs enough signal to decide if another user
    decision is required, so we send summaries and top findings instead of raw evidence.
    """

    findings = _extract_findings_from_context(profiling_context)
    severity_counts = Counter(str(item.get("severity") or "unknown") for item in findings)
    type_counts = Counter(str(item.get("type") or "unknown") for item in findings)

    selected_findings = sorted(
        findings,
        key=lambda item: _finding_priority(str(item.get("severity") or "")),
    )[:MAX_COMPACT_FINDINGS]

    compact = {
        "selected_sources": selected_sources,
        "previous_user_answers": previous_user_answers,
        "finding_counts": {
            "total": len(findings),
            "by_severity": dict(severity_counts),
            "by_type": dict(type_counts),
        },
        "top_findings": [_compact_finding(item) for item in selected_findings],
        "decision_policy": {
            "ask_at_most_one_question": True,
            "do_not_reask_answered_decisions": True,
            "treat_documentable_quality_issues_as_warnings": True,
            "only_block_when_business_definition_is_unsafe_without_user_input": True,
        },
        "profile_excerpt": _compact_markdown_excerpt(profiling_context),
    }

    rendered = json.dumps(compact, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > MAX_COMPACT_PROFILE_CHARS:
        rendered = rendered[:MAX_COMPACT_PROFILE_CHARS] + "\n... [compact profile truncated]"

    return "# Compact Source Profiling Summary\n```json\n" + rendered + "\n```"


def _extract_findings_from_context(profiling_context: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for block in re.findall(r"```json\s*(.*?)\s*```", profiling_context, flags=re.DOTALL | re.IGNORECASE):
        try:
            parsed = json.loads(block)
        except Exception:
            continue
        findings.extend(_collect_findings(parsed))

    # Fallback: extract high-signal markdown finding lines if JSON parsing did not find anything.
    if not findings:
        for line in profiling_context.splitlines():
            stripped = line.strip()
            if any(token in stripped.lower() for token in ["severity:", "duplicate", "unmatched", "overpaid", "partially paid"]):
                findings.append(
                    {
                        "id": "markdown_profile_finding",
                        "type": "profile_note",
                        "severity": "warning",
                        "message": stripped[:500],
                        "affects": ["documentation"],
                    }
                )
                if len(findings) >= MAX_COMPACT_FINDINGS:
                    break

    return findings


def _collect_findings(value: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if isinstance(value, dict):
        maybe_findings = value.get("findings") or value.get("quality_findings") or value.get("relationshipFindings")
        if isinstance(maybe_findings, list):
            for item in maybe_findings:
                if isinstance(item, dict):
                    findings.append(item)

        for nested in value.values():
            findings.extend(_collect_findings(nested))

    elif isinstance(value, list):
        for item in value:
            findings.extend(_collect_findings(item))

    return findings


def _compact_finding(finding: dict[str, Any]) -> dict[str, Any]:
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    compact_evidence = {
        key: value
        for key, value in evidence.items()
        if key.endswith("count") or key.endswith("rate") or key in {"relationship_id", "left_source", "right_source", "source", "column"}
    }

    return {
        "id": finding.get("id"),
        "type": finding.get("type"),
        "severity": finding.get("severity"),
        "message": str(finding.get("message") or "")[:500],
        "affects": finding.get("affects", []),
        "evidence": compact_evidence,
    }


def _compact_markdown_excerpt(text: str) -> str:
    lines: list[str] = []
    keep_next = 0

    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()

        if stripped.startswith("#"):
            lines.append(stripped)
            keep_next = 2
            continue

        if any(token in lower for token in ["rows:", "row count", "severity:", "duplicate", "unmatched", "partially paid", "overpaid"]):
            lines.append(stripped[:500])
            keep_next = 1
            continue

        if keep_next > 0 and stripped:
            lines.append(stripped[:500])
            keep_next -= 1

        if len("\n".join(lines)) > 2500:
            break

    return "\n".join(lines)[:2500]


def _finding_priority(severity: str) -> int:
    order = {
        "must_answer": 0,
        "error": 1,
        "warning": 2,
        "optional_review": 3,
        "info": 4,
    }
    return order.get(severity, 5)


def _validate_questions(plan: BusinessDecisionPlan) -> None:
    if plan.clarification_required and not plan.questions:
        raise ValueError("clarification_required=true but no questions were returned.")

    if len(plan.questions) > 1:
        raise ValueError("Business decision planner must ask at most one question.")

    for question in plan.questions:
        if question.options and len(question.options) < 2:
            raise ValueError(f"Question `{question.id}` has fewer than two options.")
        option_ids = [option.id for option in question.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"Question `{question.id}` has duplicate option ids.")


def _normalize_decision_plan(plan: BusinessDecisionPlan) -> BusinessDecisionPlan:
    if not plan.clarification_required:
        plan.questions = []
    elif plan.questions:
        plan.questions = plan.questions[:1]
    return plan


def _fallback_decision_plan(
    *,
    reason: str,
    previous_user_answers: list[dict[str, Any]],
    compact_context: str,
) -> BusinessDecisionPlan:
    assumptions: list[str] = []
    for answer in previous_user_answers:
        answer_text = answer.get("answer") or answer.get("selectedOptionId") or answer.get("selected_option_id")
        question_id = answer.get("questionId") or answer.get("question_id") or "previous_user_decision"
        if answer_text:
            assumptions.append(f"User decision `{question_id}`: {answer_text}")

    if not assumptions:
        assumptions.append("No additional blocking business decision was collected before artifact planning.")

    warnings = [
        reason,
        "Proceeding with existing user decisions and compact profiling warnings; detailed source and relationship profiles remain available as artifacts.",
    ]

    return BusinessDecisionPlan(
        clarification_required=False,
        questions=[],
        assumptions=assumptions[:5],
        warnings=warnings[:5],
    )


def _build_user_prompt(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    previous_user_answers: list[dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            "# User question\n" + user_question,
            "# Previous user answers\n```json\n" + json.dumps(previous_user_answers, ensure_ascii=False, indent=2, default=str) + "\n```",
            "# Validated request plan\n```json\n" + request_plan.model_dump_json(indent=2) + "\n```",
            "# Selected metadata context\n```json\n" + build_llm_metadata_prompt_context(metadata_context, selected_sources=request_plan.selected_sources) + "\n```",
            "# Compact source profiling facts\n" + profiling_context,
            "Return strict compact JSON only. Ask at most one question. If previous answers already resolve the business ambiguity, return clarification_required=false.",
        ]
    )

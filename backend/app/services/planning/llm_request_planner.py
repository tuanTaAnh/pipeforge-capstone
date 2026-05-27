from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.llm_plans import PlannerOption, PlannerQuestion, RequestPlan
from app.services.llm.llm_client import llm_client
from app.services.planning.metadata_context_builder import build_request_planner_prompt_context
from app.services.planning.planner_repair import repair_planner_json
from app.services.planning.request_plan_validator import PlanValidationError, ensure_sources_from_data_product, validate_request_plan
from app.services.runtime.flow_logger import flow_log, log_step_failure, log_step_start, log_step_success
from app.utils.prompt_loader import load_prompt_text


async def plan_request_with_llm(
    *,
    user_question: str,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]] | None = None,
    max_repair_attempts: int = 1,
    run_id: str | None = None,
) -> RequestPlan:
    previous_answers = previous_user_answers or []

    answered_plan = _try_build_plan_from_answered_clarification(
        metadata_context=metadata_context,
        previous_user_answers=previous_answers,
    )
    if answered_plan is not None:
        return _validate_and_return_precomputed_plan(
            plan=answered_plan,
            metadata_context=metadata_context,
            run_id=run_id,
            reason="config_driven_answer_resolution",
        )

    # Config-driven guard: when metadata says a request contains a known
    # must-answer ambiguity, ask the user before calling the LLM. The Python code
    # is generic; database-specific terms/options live in clarification_rules.yml.
    precomputed_plan = _try_build_config_driven_clarification_plan(
        user_question=user_question,
        metadata_context=metadata_context,
        previous_user_answers=previous_answers,
    )
    if precomputed_plan is not None:
        return _validate_and_return_precomputed_plan(
            plan=precomputed_plan,
            metadata_context=metadata_context,
            run_id=run_id,
            reason="config_driven_clarification",
        )

    system_prompt = load_prompt_text("request_planner_prompt.txt")
    user_prompt = _build_user_prompt(
        user_question=user_question,
        metadata_context=metadata_context,
        previous_user_answers=previous_answers,
    )

    try:
        raw = await llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=5000,
            run_id=run_id,
            step_id="2",
            call_name="LLM Request Planner",
        )
    except Exception as exc:
        # A provider can return incomplete text/invalid JSON. Recover only when
        # metadata rules can safely produce a clarification question. Otherwise
        # keep the original failure visible.
        fallback_plan = _try_build_config_driven_clarification_plan(
            user_question=user_question,
            metadata_context=metadata_context,
            previous_user_answers=previous_answers,
            allow_after_llm_failure=True,
        )
        if fallback_plan is not None:
            flow_log(
                run_id=run_id,
                step_id="2",
                step_name="LLM Request Planner",
                event="recovered_with_config_clarification",
                status="warning",
                details={"fallback_reason": "config_driven_clarification_after_llm_failure"},
                error=exc,
            )
            return _validate_and_return_precomputed_plan(
                plan=fallback_plan,
                metadata_context=metadata_context,
                run_id=run_id,
                reason="config_driven_clarification_after_llm_failure",
            )
        raise

    for attempt in range(max_repair_attempts + 1):
        validation_timer = log_step_start(
            run_id,
            "3",
            "Validate request planner output",
            {"attempt": attempt + 1, "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else None},
        )
        try:
            plan = RequestPlan.model_validate(raw)
            plan = ensure_sources_from_data_product(plan, metadata_context)
            validate_request_plan(plan, metadata_context)
            log_step_success(
                run_id,
                "3",
                "Validate request planner output",
                started_at=validation_timer,
                details={
                    "request_type": plan.request_type,
                    "clarification_required": plan.clarification_required,
                    "selected_sources": plan.selected_sources,
                    "selected_metrics": plan.selected_metrics,
                    "selected_dimensions": plan.selected_dimensions,
                    "selected_data_product": plan.selected_data_product,
                },
            )
            return plan
        except Exception as exc:
            errors = getattr(exc, "errors", None)
            if callable(errors):
                validation_errors = [str(item) for item in errors()]
            elif isinstance(exc, PlanValidationError):
                validation_errors = exc.errors
            else:
                validation_errors = [str(exc)]

            log_step_failure(
                run_id,
                "3",
                "Validate request planner output",
                started_at=validation_timer,
                error=exc,
                details={"attempt": attempt + 1, "validation_errors": validation_errors},
            )

            if attempt >= max_repair_attempts:
                raise

            raw = await repair_planner_json(
                original_system_prompt=system_prompt,
                original_user_prompt=user_prompt,
                invalid_output=raw if isinstance(raw, dict) else {"raw": raw},
                validation_errors=validation_errors,
                max_output_tokens=5000,
                run_id=run_id,
                step_id="3-repair",
            )

    raise RuntimeError("Request planner failed unexpectedly.")


def _build_user_prompt(
    *,
    user_question: str,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            "# User question\n" + user_question,
            "# Previous user answers\n```json\n" + json.dumps(previous_user_answers, ensure_ascii=False, indent=2, default=str) + "\n```",
            "# Compact metadata context for request planning\n```json\n" + build_request_planner_prompt_context(metadata_context) + "\n```",
            "Return strict compact JSON only.",
        ]
    )


def _validate_and_return_precomputed_plan(
    *,
    plan: RequestPlan,
    metadata_context: dict[str, Any],
    run_id: str | None,
    reason: str,
) -> RequestPlan:
    validation_timer = log_step_start(
        run_id,
        "3",
        "Validate request planner output",
        {"attempt": 1, "source": reason, "raw_keys": sorted(plan.model_dump().keys())},
    )
    plan = ensure_sources_from_data_product(plan, metadata_context)
    validate_request_plan(plan, metadata_context)
    log_step_success(
        run_id,
        "3",
        "Validate request planner output",
        started_at=validation_timer,
        details={
            "source": reason,
            "request_type": plan.request_type,
            "clarification_required": plan.clarification_required,
            "selected_sources": plan.selected_sources,
            "selected_metrics": plan.selected_metrics,
            "selected_dimensions": plan.selected_dimensions,
            "selected_data_product": plan.selected_data_product,
        },
    )
    return plan


def _try_build_plan_from_answered_clarification(
    *,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
) -> RequestPlan | None:
    for answer in reversed(previous_user_answers):
        if not isinstance(answer, dict):
            continue

        question_id = str(answer.get("questionId") or answer.get("question_id") or "").strip()
        selected_option_id = str(answer.get("selectedOptionId") or answer.get("selected_option_id") or "").strip()
        if not question_id or not selected_option_id:
            continue

        for rule in metadata_context.get("clarification_rules", []):
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue

            clarification = rule.get("clarification") if isinstance(rule.get("clarification"), dict) else {}
            rule_question_id = str(clarification.get("id") or rule.get("id") or "").strip()
            if rule_question_id != question_id:
                continue

            for option in _rule_options(rule):
                if str(option.get("id") or "").strip() != selected_option_id:
                    continue

                plan = _build_plan_from_answered_option(
                    rule=rule,
                    option=option,
                    metadata_context=metadata_context,
                    answer=answer,
                )
                if plan is not None:
                    return plan

    return None


def _build_plan_from_answered_option(
    *,
    rule: dict[str, Any],
    option: dict[str, Any],
    metadata_context: dict[str, Any],
    answer: dict[str, Any],
) -> RequestPlan | None:
    defaults = rule.get("plan_defaults") if isinstance(rule.get("plan_defaults"), dict) else {}

    selected_sources = _valid_items(option.get("selected_sources"), metadata_context.get("allowed_sources", []))
    selected_metrics = _valid_items(option.get("selected_metrics"), metadata_context.get("allowed_metrics", []))
    selected_dimensions = _valid_items(option.get("selected_dimensions"), metadata_context.get("allowed_dimensions", []))
    selected_data_product = _valid_optional_item(option.get("selected_data_product"), metadata_context.get("allowed_data_products", []))

    if not selected_sources and not selected_data_product:
        selected_sources = _valid_items(defaults.get("selected_sources"), metadata_context.get("allowed_sources", []))
        selected_data_product = _valid_optional_item(defaults.get("selected_data_product"), metadata_context.get("allowed_data_products", []))

    if not selected_sources and not selected_data_product:
        return None

    option_label = str(option.get("label") or option.get("id") or "selected option")
    resolved_rule = str(option.get("resolved_rule") or answer.get("answer") or option_label).strip()
    implementation = str(option.get("implementation") or resolved_rule).strip()

    return RequestPlan(
        request_type=str(defaults.get("request_type") or "data_product_generation"),
        clarification_required=False,
        clarification_question=None,
        selected_sources=selected_sources,
        selected_metrics=selected_metrics,
        selected_dimensions=selected_dimensions,
        selected_data_product=selected_data_product,
        business_interpretation=resolved_rule,
        assumptions=_as_string_list(defaults.get("assumptions")) + [f"User selected: {option_label}"],
        warnings=_as_string_list(option.get("warnings")),
        reasoning_summary=implementation,
    )


def _try_build_config_driven_clarification_plan(
    *,
    user_question: str,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
    allow_after_llm_failure: bool = False,
) -> RequestPlan | None:
    del allow_after_llm_failure  # Kept for readability at call sites.

    text = _normalize(user_question)
    answered_question_ids = {
        str(answer.get("questionId") or answer.get("question_id") or "").strip()
        for answer in previous_user_answers
        if isinstance(answer, dict)
    }

    for rule in metadata_context.get("clarification_rules", []):
        if not isinstance(rule, dict) or not rule.get("enabled", True):
            continue

        clarification = rule.get("clarification") if isinstance(rule.get("clarification"), dict) else {}
        question_id = str(clarification.get("id") or rule.get("id") or "").strip()
        if question_id and question_id in answered_question_ids:
            continue

        if not _rule_matches(text, rule):
            continue

        plan = _build_plan_from_rule(rule=rule, metadata_context=metadata_context)
        if plan is not None:
            return plan

    return None


def _rule_matches(text: str, rule: dict[str, Any]) -> bool:
    match_config = rule.get("match") if isinstance(rule.get("match"), dict) else {}

    all_any = match_config.get("all_any", {})
    if isinstance(all_any, dict):
        for terms in all_any.values():
            if not _contains_any(text, _as_string_list(terms)):
                return False

    any_any = match_config.get("any_any", {})
    if isinstance(any_any, dict) and any_any:
        if not any(_contains_any(text, _as_string_list(terms)) for terms in any_any.values()):
            return False

    none_any = match_config.get("none_any", {})
    if isinstance(none_any, dict):
        for terms in none_any.values():
            if _contains_any(text, _as_string_list(terms)):
                return False

    if bool(match_config.get("missing_explicit_choice_from_options", False)):
        if _request_contains_explicit_option_choice(text, rule):
            return False

    return True


def _request_contains_explicit_option_choice(text: str, rule: dict[str, Any]) -> bool:
    options = rule.get("options", [])
    if not isinstance(options, list):
        return False

    for option in options:
        if not isinstance(option, dict):
            continue
        explicit_terms = []
        explicit_terms.extend(_as_string_list(option.get("aliases")))
        explicit_terms.append(str(option.get("id", "")))
        explicit_terms.append(str(option.get("label", "")))
        explicit_terms = [term for term in explicit_terms if term.strip()]
        if _contains_any(text, explicit_terms):
            return True

    return False


def _build_plan_from_rule(*, rule: dict[str, Any], metadata_context: dict[str, Any]) -> RequestPlan | None:
    defaults = rule.get("plan_defaults") if isinstance(rule.get("plan_defaults"), dict) else {}
    clarification = rule.get("clarification") if isinstance(rule.get("clarification"), dict) else {}

    options = _build_planner_options(rule)
    if not clarification.get("question") or not options:
        return None

    selected_sources = _valid_items(defaults.get("selected_sources"), metadata_context.get("allowed_sources", []))
    selected_metrics = _valid_items(defaults.get("selected_metrics"), metadata_context.get("allowed_metrics", []))
    selected_dimensions = _valid_items(defaults.get("selected_dimensions"), metadata_context.get("allowed_dimensions", []))
    selected_data_product = _valid_optional_item(defaults.get("selected_data_product"), metadata_context.get("allowed_data_products", []))

    # If the rule did not define defaults, use the union of valid option-level
    # selections so validation can pass while the system is waiting for the user.
    if not selected_sources:
        selected_sources = _union_valid_option_items(rule, "selected_sources", metadata_context.get("allowed_sources", []))
    if not selected_metrics:
        selected_metrics = _union_valid_option_items(rule, "selected_metrics", metadata_context.get("allowed_metrics", []))
    if not selected_dimensions:
        selected_dimensions = _union_valid_option_items(rule, "selected_dimensions", metadata_context.get("allowed_dimensions", []))

    if not selected_sources and not selected_data_product:
        return None

    question = PlannerQuestion(
        id=str(clarification.get("id") or rule.get("id") or "q_metadata_clarification"),
        issue_id=_optional_str(clarification.get("issue_id") or clarification.get("issueId") or rule.get("id")),
        question=str(clarification.get("question")),
        issue_summary=_optional_str(clarification.get("issue_summary")),
        priority=str(clarification.get("priority") or "must_answer"),
        recommended_option_id=_optional_str(clarification.get("recommended_option_id")) or (options[0].id if options else None),
        recommendation_reason=_optional_str(clarification.get("recommendation_reason")),
        options=options,
        allow_custom_answer=bool(clarification.get("allow_custom_answer", True)),
    )

    return RequestPlan(
        request_type=str(defaults.get("request_type") or "clarification"),
        clarification_required=True,
        clarification_question=question,
        selected_sources=selected_sources,
        selected_metrics=selected_metrics,
        selected_dimensions=selected_dimensions,
        selected_data_product=selected_data_product,
        business_interpretation=str(defaults.get("business_interpretation") or "Clarify the business definition before continuing."),
        assumptions=_as_string_list(defaults.get("assumptions")),
        warnings=_as_string_list(defaults.get("warnings")),
        reasoning_summary=str(rule.get("description") or "Metadata rule requires user clarification."),
    )


def _rule_options(rule: dict[str, Any]) -> list[dict[str, Any]]:
    options = rule.get("options", [])
    return [option for option in options if isinstance(option, dict)] if isinstance(options, list) else []


def _build_planner_options(rule: dict[str, Any]) -> list[PlannerOption]:
    raw_options = rule.get("options", [])
    if not isinstance(raw_options, list):
        return []

    options: list[PlannerOption] = []
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("id", "")).strip()
        label = str(option.get("label", "")).strip()
        if not option_id or not label:
            continue
        options.append(
            PlannerOption(
                id=option_id,
                label=label,
                description=_optional_str(option.get("description")),
                resolved_rule=_optional_str(option.get("resolved_rule")),
                implementation=_optional_str(option.get("implementation")),
            )
        )
    return options


def _union_valid_option_items(rule: dict[str, Any], field_name: str, allowed_items: list[str]) -> list[str]:
    values: list[str] = []
    options = rule.get("options", [])
    if not isinstance(options, list):
        return values

    for option in options:
        if isinstance(option, dict):
            values.extend(_valid_items(option.get(field_name), allowed_items))

    return _dedupe(values)


def _valid_items(value: Any, allowed_items: list[str]) -> list[str]:
    allowed = set(str(item) for item in allowed_items)
    return _dedupe([item for item in _as_string_list(value) if item in allowed])


def _valid_optional_item(value: Any, allowed_items: list[str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if text in set(str(item) for item in allowed_items) else None


def _contains_any(text: str, terms: list[str]) -> bool:
    normalized_terms = [_normalize(term) for term in terms if _normalize(term)]
    return any(term in text for term in normalized_terms)


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^a-z0-9_\s/-]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()
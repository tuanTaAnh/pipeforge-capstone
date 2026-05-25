from __future__ import annotations

import json
from typing import Any

from app.schemas.llm_plans import ArtifactPlan, RequestPlan
from app.services.llm.llm_client import llm_client
from app.services.planning.artifact_plan_validator import ArtifactPlanValidationError, normalize_artifact_plan, validate_artifact_plan
from app.services.planning.data_product_plan_builder import build_data_product_artifact_plan
from app.services.planning.llm_business_decision_planner import compact_profile_context_for_business_decisions
from app.services.planning.planner_repair import repair_planner_json
from app.services.runtime.flow_logger import flow_log, log_step_failure, log_step_start, log_step_success, summarize_text
from app.utils.prompt_loader import load_prompt_text


async def plan_artifacts_with_llm(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    business_rules_context: str,
    previous_user_answers: list[dict[str, Any]] | None = None,
    max_repair_attempts: int = 1,
    run_id: str | None = None,
) -> ArtifactPlan:
    """Create the Step 8B artifact plan.

    The LLM is useful for concise business wording, but the actual package/file
    structure should remain contract-driven. If the LLM returns incomplete JSON
    or spends all output budget on reasoning, we fall back to a deterministic
    plan built from the selected data product YAML instead of failing the run.
    """

    system_prompt = load_prompt_text("artifact_planner_prompt.txt")
    deterministic_plan = build_data_product_artifact_plan(
        request_plan=request_plan,
        metadata_context=metadata_context,
        business_rules_context=business_rules_context,
    )
    deterministic_plan = normalize_artifact_plan(deterministic_plan, request_plan)
    validate_artifact_plan(deterministic_plan, request_plan, metadata_context)

    user_prompt = _build_user_prompt(
        user_question=user_question,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=compact_profile_context_for_business_decisions(
            profiling_context=profiling_context,
            selected_sources=request_plan.selected_sources,
            previous_user_answers=previous_user_answers or [],
        ),
        business_rules_context=business_rules_context,
        previous_user_answers=previous_user_answers or [],
        default_artifact_plan=deterministic_plan.as_artifact_plan_dict(),
    )

    try:
        raw = await llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=5000,
            run_id=run_id,
            step_id="8B",
            call_name="LLM Artifact Planner",
        )
    except Exception as exc:
        _log_artifact_plan_fallback(
            run_id=run_id,
            reason=str(exc),
            fallback_plan=deterministic_plan,
            stage="llm_call_failed",
        )
        return deterministic_plan

    for attempt in range(max_repair_attempts + 1):
        validation_timer = log_step_start(
            run_id,
            "8B-validate",
            "Validate artifact plan",
            {
                "attempt": attempt + 1,
                "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else None,
            },
        )
        try:
            plan = ArtifactPlan.model_validate(raw)
            plan = normalize_artifact_plan(plan, request_plan)
            validate_artifact_plan(plan, request_plan, metadata_context)
            log_step_success(
                run_id,
                "8B-validate",
                "Validate artifact plan",
                started_at=validation_timer,
                details={
                    "model_files": plan.model_files,
                    "test_files": plan.test_files,
                    "documentation_files": plan.documentation_files,
                },
            )
            return plan
        except Exception as exc:
            errors = getattr(exc, "errors", None)
            if callable(errors):
                validation_errors = [str(item) for item in errors()]
            elif isinstance(exc, ArtifactPlanValidationError):
                validation_errors = exc.errors
            else:
                validation_errors = [str(exc)]

            log_step_failure(
                run_id,
                "8B-validate",
                "Validate artifact plan",
                started_at=validation_timer,
                error=exc,
                details={
                    "attempt": attempt + 1,
                    "validation_errors": validation_errors,
                },
            )

            if attempt >= max_repair_attempts:
                _log_artifact_plan_fallback(
                    run_id=run_id,
                    reason="; ".join(validation_errors),
                    fallback_plan=deterministic_plan,
                    stage="validation_failed",
                )
                return deterministic_plan

            try:
                raw = await repair_planner_json(
                    original_system_prompt=system_prompt,
                    original_user_prompt=user_prompt,
                    invalid_output=raw if isinstance(raw, dict) else {"raw": raw},
                    validation_errors=validation_errors,
                    max_output_tokens=5000,
                    run_id=run_id,
                    step_id="8B-repair",
                )
            except Exception as repair_exc:
                _log_artifact_plan_fallback(
                    run_id=run_id,
                    reason=str(repair_exc),
                    fallback_plan=deterministic_plan,
                    stage="repair_failed",
                )
                return deterministic_plan

    return deterministic_plan


def _build_user_prompt(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    business_rules_context: str,
    previous_user_answers: list[dict[str, Any]],
    default_artifact_plan: dict[str, Any],
) -> str:
    selected_data_product = request_plan.selected_data_product or ""
    data_product_contract = _selected_data_product_context(metadata_context, selected_data_product)

    prompt_payload = {
        "user_request": user_question,
        "previous_user_answers": previous_user_answers,
        "validated_request_plan": request_plan.model_dump(mode="json"),
        "selected_sources": request_plan.selected_sources,
        "selected_data_product": selected_data_product,
        "data_product_contract": data_product_contract,
        "default_artifact_plan_from_contract": default_artifact_plan,
        "compact_source_profile": _truncate_text(profiling_context, max_chars=3000),
        "resolved_business_rules": _truncate_text(business_rules_context, max_chars=2500),
    }

    return (
        "Create a compact artifact_plan.json from this payload. "
        "Prefer default_artifact_plan_from_contract for package/file structure.\n\n"
        "```json\n"
        + json.dumps(prompt_payload, ensure_ascii=False, indent=2, default=str)
        + "\n```\n\n"
        "Return raw JSON only, following the exact schema and length limits in the system prompt."
    )


def _selected_data_product_context(metadata_context: dict[str, Any], selected_data_product: str) -> dict[str, Any]:
    data_products = metadata_context.get("data_products")
    if not isinstance(data_products, dict):
        return {}

    product = data_products.get(selected_data_product)
    if not isinstance(product, dict):
        return {}

    return {
        "name": product.get("name"),
        "package_name": product.get("package_name"),
        "description": product.get("description"),
        "sources": product.get("sources", []),
        "primary_source": product.get("primary_source"),
        "relationships": product.get("relationships", []),
        "grain": product.get("grain", []),
        "metrics": product.get("metrics", []),
        "known_business_questions": product.get("known_business_questions", []),
        "artifact_plan_examples": product.get("artifact_plan_examples", {}),
    }


def _truncate_text(value: str, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _log_artifact_plan_fallback(
    *,
    run_id: str | None,
    reason: str,
    fallback_plan: ArtifactPlan,
    stage: str,
) -> None:
    flow_log(
        run_id=run_id,
        step_id="8B",
        step_name="LLM creates artifact_plan.json",
        event="fallback",
        status="warning",
        details={
            "stage": stage,
            "reason": summarize_text(reason, max_chars=800),
            "fallback_plan": fallback_plan.as_artifact_plan_dict(),
        },
    )
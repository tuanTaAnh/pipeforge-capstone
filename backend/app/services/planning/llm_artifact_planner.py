from __future__ import annotations

import json
from typing import Any

from app.schemas.llm_plans import ArtifactPlan, RequestPlan
from app.services.llm.llm_client import llm_client
from app.services.planning.artifact_plan_validator import ArtifactPlanValidationError, normalize_artifact_plan, validate_artifact_plan
from app.services.planning.metadata_context_builder import build_llm_metadata_prompt_context
from app.services.planning.planner_repair import repair_planner_json
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
) -> ArtifactPlan:
    system_prompt = load_prompt_text("artifact_planner_prompt.txt")
    user_prompt = _build_user_prompt(
        user_question=user_question,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=profiling_context,
        business_rules_context=business_rules_context,
        previous_user_answers=previous_user_answers or [],
    )
    raw = await llm_client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=6000)

    for attempt in range(max_repair_attempts + 1):
        try:
            plan = ArtifactPlan.model_validate(raw)
            plan = normalize_artifact_plan(plan, request_plan)
            validate_artifact_plan(plan, request_plan, metadata_context)
            return plan
        except Exception as exc:
            errors = getattr(exc, "errors", None)
            if callable(errors):
                validation_errors = [str(item) for item in errors()]
            elif isinstance(exc, ArtifactPlanValidationError):
                validation_errors = exc.errors
            else:
                validation_errors = [str(exc)]

            if attempt >= max_repair_attempts:
                raise

            raw = await repair_planner_json(
                original_system_prompt=system_prompt,
                original_user_prompt=user_prompt,
                invalid_output=raw if isinstance(raw, dict) else {"raw": raw},
                validation_errors=validation_errors,
                max_output_tokens=6000,
            )

    raise RuntimeError("Artifact planner failed unexpectedly.")


def _build_user_prompt(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    business_rules_context: str,
    previous_user_answers: list[dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            "# User question\n" + user_question,
            "# Previous user answers\n```json\n" + json.dumps(previous_user_answers, ensure_ascii=False, indent=2, default=str) + "\n```",
            "# Validated request plan\n```json\n" + request_plan.model_dump_json(indent=2) + "\n```",
            "# Selected metadata context\n```json\n" + build_llm_metadata_prompt_context(metadata_context, selected_sources=request_plan.selected_sources) + "\n```",
            "# Source profiling facts\n" + profiling_context,
            "# Business rules context\n" + business_rules_context,
            "Return strict JSON only.",
        ]
    )

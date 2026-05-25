from __future__ import annotations

import json
from typing import Any

from app.schemas.llm_plans import RequestPlan
from app.services.llm.llm_client import llm_client
from app.services.planning.metadata_context_builder import build_llm_metadata_prompt_context
from app.services.planning.planner_repair import repair_planner_json
from app.services.planning.request_plan_validator import PlanValidationError, ensure_sources_from_data_product, validate_request_plan
from app.services.runtime.flow_logger import log_step_failure, log_step_start, log_step_success
from app.utils.prompt_loader import load_prompt_text


async def plan_request_with_llm(
    *,
    user_question: str,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]] | None = None,
    max_repair_attempts: int = 1,
    run_id: str | None = None,
) -> RequestPlan:
    system_prompt = load_prompt_text("request_planner_prompt.txt")
    user_prompt = _build_user_prompt(
        user_question=user_question,
        metadata_context=metadata_context,
        previous_user_answers=previous_user_answers or [],
    )

    raw = await llm_client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=5000,
        run_id=run_id,
        step_id="2",
        call_name="LLM Request Planner",
    )

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
            "# Metadata context\n```json\n" + build_llm_metadata_prompt_context(metadata_context) + "\n```",
            "Return strict JSON only.",
        ]
    )

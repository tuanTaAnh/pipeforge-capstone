from __future__ import annotations

import json
from typing import Any

from app.schemas.llm_plans import DirectQueryPlan, RequestPlan
from app.services.llm.llm_client import llm_client
from app.services.planning.direct_query_validator import DirectQueryValidationError, validate_direct_query_sql
from app.services.planning.metadata_context_builder import build_llm_metadata_prompt_context
from app.services.planning.planner_repair import repair_planner_json
from app.services.runtime.flow_logger import log_step_failure, log_step_start, log_step_success
from app.utils.prompt_loader import load_prompt_text


async def plan_direct_query_with_llm(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]] | None = None,
    max_repair_attempts: int = 1,
    run_id: str | None = None,
) -> DirectQueryPlan:
    system_prompt = load_prompt_text("direct_query_planner_prompt.txt")
    user_prompt = _build_user_prompt(
        user_question=user_question,
        request_plan=request_plan,
        metadata_context=metadata_context,
        previous_user_answers=previous_user_answers or [],
    )
    raw = await llm_client.generate_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_output_tokens=5000,
        run_id=run_id,
        step_id="5A",
        call_name="LLM Direct Query Planner",
    )

    for attempt in range(max_repair_attempts + 1):
        validation_timer = log_step_start(run_id, "6A", "Validate direct SQL plan", {"attempt": attempt + 1, "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else None})
        try:
            plan = DirectQueryPlan.model_validate(raw)
            validate_direct_query_sql(
                sql=plan.sql,
                metadata_context=metadata_context,
                selected_sources=request_plan.selected_sources,
            )
            log_step_success(run_id, "6A", "Validate direct SQL plan", started_at=validation_timer, details={"sql_preview": plan.sql[:500], "selected_sources": request_plan.selected_sources})
            return plan
        except Exception as exc:
            errors = getattr(exc, "errors", None)
            if callable(errors):
                validation_errors = [str(item) for item in errors()]
            elif isinstance(exc, DirectQueryValidationError):
                validation_errors = exc.errors
            else:
                validation_errors = [str(exc)]

            log_step_failure(run_id, "6A", "Validate direct SQL plan", started_at=validation_timer, error=exc, details={"attempt": attempt + 1, "validation_errors": validation_errors})

            if attempt >= max_repair_attempts:
                raise

            raw = await repair_planner_json(
                original_system_prompt=system_prompt,
                original_user_prompt=user_prompt,
                invalid_output=raw if isinstance(raw, dict) else {"raw": raw},
                validation_errors=validation_errors,
                max_output_tokens=5000,
                run_id=run_id,
                step_id="6A-repair",
            )

    raise RuntimeError("Direct query planner failed unexpectedly.")


def _build_user_prompt(
    *,
    user_question: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            "# User question\n" + user_question,
            "# Previous user answers\n```json\n" + json.dumps(previous_user_answers, ensure_ascii=False, indent=2, default=str) + "\n```",
            "# Validated request plan\n```json\n" + request_plan.model_dump_json(indent=2) + "\n```",
            "# Selected metadata context\n```json\n" + build_llm_metadata_prompt_context(metadata_context, selected_sources=request_plan.selected_sources) + "\n```",
            "Return strict JSON only.",
        ]
    )

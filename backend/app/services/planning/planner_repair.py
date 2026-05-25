from __future__ import annotations

import json
from typing import Any

from app.services.llm.llm_client import llm_client
from app.utils.prompt_loader import load_prompt_text


async def repair_planner_json(
    *,
    original_system_prompt: str,
    original_user_prompt: str,
    invalid_output: dict[str, Any],
    validation_errors: list[str],
    max_output_tokens: int = 4000,
) -> dict[str, Any]:
    repair_prompt = load_prompt_text("planner_repair_prompt.txt")
    user_prompt = repair_prompt.replace("{{ORIGINAL_SYSTEM_PROMPT}}", original_system_prompt)
    user_prompt = user_prompt.replace("{{ORIGINAL_USER_PROMPT}}", original_user_prompt)
    user_prompt = user_prompt.replace(
        "{{INVALID_OUTPUT_JSON}}",
        json.dumps(invalid_output, ensure_ascii=False, indent=2, default=str),
    )
    user_prompt = user_prompt.replace(
        "{{VALIDATION_ERRORS_JSON}}",
        json.dumps(validation_errors, ensure_ascii=False, indent=2, default=str),
    )

    return await llm_client.generate_json(
        system_prompt="You repair invalid PipeForge planner JSON. Return corrected JSON only.",
        user_prompt=user_prompt,
        max_output_tokens=max_output_tokens,
    )

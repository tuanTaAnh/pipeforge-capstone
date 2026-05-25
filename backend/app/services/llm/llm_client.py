import json
import re
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.services.runtime.flow_logger import flow_log, log_step_failure, log_step_start, log_step_success, summarize_text


class LLMResponseTextExtractionError(RuntimeError):
    """Raised when the LLM provider returns no extractable text content."""

    def __init__(self, message: str, *, status: str | None = None, incomplete_reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.incomplete_reason = incomplete_reason


def _provider_usage_summary(data: Dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    output_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
    incomplete_details = data.get("incomplete_details") if isinstance(data.get("incomplete_details"), dict) else {}
    return {
        "provider_status": data.get("status"),
        "incomplete_reason": incomplete_details.get("reason"),
        "model": data.get("model"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": output_details.get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _extract_text_from_response(data: Dict[str, Any]) -> str:
    """
    Supports common OpenAI Responses-style shapes and fallback chat-completions shapes.

    Important: some reasoning models can return status='incomplete' with only reasoning
    tokens and no final text. In that case we raise a compact, typed error instead of
    dumping the entire raw provider response into the application error stream.
    """

    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"]

    output = data.get("output")
    if isinstance(output, list):
        parts = []

        for item in output:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue

                    if isinstance(block.get("text"), str) and block["text"].strip():
                        parts.append(block["text"])

                    if isinstance(block.get("content"), str) and block["content"].strip():
                        parts.append(block["content"])

            if isinstance(item.get("text"), str) and item["text"].strip():
                parts.append(item["text"])

        if parts:
            return "\n".join(parts)

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str) and message["content"].strip():
                return message["content"]

            if isinstance(first.get("text"), str) and first["text"].strip():
                return first["text"]

    status = str(data.get("status") or "") or None
    incomplete_reason = None
    incomplete_details = data.get("incomplete_details")
    if isinstance(incomplete_details, dict):
        incomplete_reason = str(incomplete_details.get("reason") or "") or None

    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    reasoning_tokens = (usage.get("output_tokens_details") or {}).get("reasoning_tokens") if isinstance(usage.get("output_tokens_details"), dict) else None

    details = []
    if status:
        details.append(f"status={status}")
    if incomplete_reason:
        details.append(f"reason={incomplete_reason}")
    if input_tokens is not None:
        details.append(f"input_tokens={input_tokens}")
    if output_tokens is not None:
        details.append(f"output_tokens={output_tokens}")
    if reasoning_tokens is not None:
        details.append(f"reasoning_tokens={reasoning_tokens}")

    suffix = f" ({', '.join(details)})" if details else ""
    raise LLMResponseTextExtractionError(
        f"Could not extract text from LLM response{suffix}.",
        status=status,
        incomplete_reason=incomplete_reason,
    )


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("LLM output JSON is not an object")
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"LLM did not return valid JSON:\n{cleaned}")

        sliced = cleaned[start : end + 1]
        parsed = json.loads(sliced)

        if not isinstance(parsed, dict):
            raise RuntimeError("LLM JSON output is not an object")

        return parsed


class LLMClient:
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 4000,
        *,
        run_id: str | None = None,
        step_id: str = "LLM",
        call_name: str = "llm_generate_json",
    ) -> Dict[str, Any]:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is missing")

        if not settings.llm_model:
            raise RuntimeError("LLM_MODEL is missing")

        started_at = log_step_start(
            run_id,
            step_id,
            call_name,
            {
                "model": settings.llm_model,
                "max_output_tokens": max_output_tokens,
                "system_prompt": summarize_text(system_prompt, max_chars=1200),
                "user_prompt": summarize_text(user_prompt, max_chars=2000),
            },
        )

        payload = {
            "model": settings.llm_model,
            "input": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "max_output_tokens": max_output_tokens,
        }

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    settings.responses_url,
                    headers=headers,
                    json=payload,
                )

            if response.status_code >= 400:
                raise RuntimeError(
                    f"LLM request failed with status={response.status_code}: {response.text}"
                )

            data = response.json()
            usage_summary = _provider_usage_summary(data)
            flow_log(
                run_id=run_id,
                step_id=step_id,
                step_name=call_name,
                event="provider_response",
                status="completed" if usage_summary.get("provider_status") != "incomplete" else "warning",
                details=usage_summary,
            )
            text = _extract_text_from_response(data)
            parsed = _parse_json_object(text)
            log_step_success(
                run_id,
                step_id,
                call_name,
                started_at=started_at,
                details={
                    "text": summarize_text(text, max_chars=1600),
                    "json_keys": sorted(parsed.keys()),
                    "usage": usage_summary,
                },
            )
            return parsed
        except Exception as exc:
            log_step_failure(
                run_id,
                step_id,
                call_name,
                started_at=started_at,
                error=exc,
                details={
                    "model": settings.llm_model,
                    "max_output_tokens": max_output_tokens,
                    "system_prompt_chars": len(system_prompt),
                    "user_prompt_chars": len(user_prompt),
                },
            )
            raise


llm_client = LLMClient()

import json
import re
from typing import Any, Dict

import httpx

from app.core.config import settings


def _extract_text_from_response(data: Dict[str, Any]) -> str:
    """
    Supports common OpenAI Responses-style shapes and fallback chat-completions shapes.
    """

    if isinstance(data.get("output_text"), str):
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

                    if isinstance(block.get("text"), str):
                        parts.append(block["text"])

                    if isinstance(block.get("content"), str):
                        parts.append(block["content"])

            if isinstance(item.get("text"), str):
                parts.append(item["text"])

        if parts:
            return "\n".join(parts)

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]

            if isinstance(first.get("text"), str):
                return first["text"]

    raise RuntimeError(f"Could not extract text from LLM response: {data}")


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
    ) -> Dict[str, Any]:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY is missing")

        if not settings.llm_model:
            raise RuntimeError("LLM_MODEL is missing")

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
        text = _extract_text_from_response(data)
        return _parse_json_object(text)


llm_client = LLMClient()
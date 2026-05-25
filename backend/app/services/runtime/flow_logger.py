from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any


MAX_STRING_CHARS = 2500
MAX_LIST_ITEMS = 25
MAX_DICT_ITEMS = 80
MAX_DEPTH = 5


def start_timer() -> float:
    return time.perf_counter()


def elapsed_ms(started_at: float | None) -> int | None:
    if started_at is None:
        return None
    return int((time.perf_counter() - started_at) * 1000)


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Conservative rough estimate for logs only. Provider usage is logged separately when available.
    return max(1, len(text) // 4)


def summarize_text(text: str | None, *, max_chars: int = MAX_STRING_CHARS) -> dict[str, Any]:
    text = text or ""
    preview = text[:max_chars]
    return {
        "char_count": len(text),
        "estimated_tokens": estimate_tokens(text),
        "truncated": len(text) > max_chars,
        "preview": preview + ("... [truncated]" if len(text) > max_chars else ""),
    }


def compact_for_log(value: Any, *, depth: int = MAX_DEPTH) -> Any:
    if depth <= 0:
        return _compact_leaf(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        if len(value) <= MAX_STRING_CHARS:
            return value
        return {
            "char_count": len(value),
            "estimated_tokens": estimate_tokens(value),
            "preview": value[:MAX_STRING_CHARS] + "... [truncated]",
        }

    if isinstance(value, dict):
        items = list(value.items())
        compacted: dict[str, Any] = {}
        for key, item_value in items[:MAX_DICT_ITEMS]:
            compacted[str(key)] = compact_for_log(item_value, depth=depth - 1)
        if len(items) > MAX_DICT_ITEMS:
            compacted["__truncated_keys__"] = len(items) - MAX_DICT_ITEMS
        return compacted

    if isinstance(value, (list, tuple, set)):
        values = list(value)
        compacted_values = [compact_for_log(item, depth=depth - 1) for item in values[:MAX_LIST_ITEMS]]
        if len(values) > MAX_LIST_ITEMS:
            compacted_values.append({"__truncated_items__": len(values) - MAX_LIST_ITEMS})
        return compacted_values

    try:
        return compact_for_log(value.model_dump(), depth=depth - 1)  # type: ignore[attr-defined]
    except Exception:
        return _compact_leaf(value)


def _compact_leaf(value: Any) -> Any:
    text = str(value)
    if len(text) <= MAX_STRING_CHARS:
        return text
    return {
        "type": type(value).__name__,
        "char_count": len(text),
        "preview": text[:MAX_STRING_CHARS] + "... [truncated]",
    }


def flow_log(
    *,
    run_id: str | None,
    step_id: str,
    step_name: str,
    event: str,
    status: str = "info",
    details: dict[str, Any] | None = None,
    error: BaseException | str | None = None,
    started_at: float | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "step_id": step_id,
        "step_name": step_name,
        "event": event,
        "status": status,
    }

    duration = elapsed_ms(started_at)
    if duration is not None:
        payload["duration_ms"] = duration

    if details:
        payload["details"] = compact_for_log(details)

    if error is not None:
        if isinstance(error, BaseException):
            payload["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exception_only(type(error), error)[-1].strip(),
            }
        else:
            payload["error"] = {"message": str(error)}

    print("[PF FLOW] " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def log_step_start(run_id: str | None, step_id: str, step_name: str, details: dict[str, Any] | None = None) -> float:
    started_at = start_timer()
    flow_log(run_id=run_id, step_id=step_id, step_name=step_name, event="start", status="running", details=details)
    return started_at


def log_step_success(
    run_id: str | None,
    step_id: str,
    step_name: str,
    *,
    started_at: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    flow_log(run_id=run_id, step_id=step_id, step_name=step_name, event="success", status="completed", details=details, started_at=started_at)


def log_step_failure(
    run_id: str | None,
    step_id: str,
    step_name: str,
    *,
    started_at: float | None = None,
    error: BaseException | str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    flow_log(run_id=run_id, step_id=step_id, step_name=step_name, event="failure", status="failed", details=details, error=error, started_at=started_at)

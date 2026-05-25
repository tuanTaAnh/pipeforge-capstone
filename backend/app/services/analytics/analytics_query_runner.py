from __future__ import annotations

import json
from typing import Any

from app.schemas.agents import AgentInfo
from app.schemas.llm_plans import RequestPlan
from app.services.artifacts.artifact_store import artifact_store
from app.services.database.database_service import fetch_all
from app.services.planning.llm_direct_query_planner import plan_direct_query_with_llm
from app.services.runtime.event_emitter import event_emitter
from app.services.runtime.flow_logger import log_step_failure, log_step_start, log_step_success


ANALYTICS_AGENT = AgentInfo(
    id="analytics-query-agent",
    name="Analytics Query Agent",
    role="sub_agent",
    parentId="pipeline-architect",
)


async def run_direct_analytics_query(
    run_id: str,
    prompt: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    flow_timer = log_step_start(run_id, "5A", "Direct Analytics Flow", {"selected_sources": request_plan.selected_sources, "prompt": prompt})
    await event_emitter.emit(run_id, "sub_agent_started", ANALYTICS_AGENT, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        ANALYTICS_AGENT,
        {
            "text": (
                "I will use an LLM direct-query planner with the validated metadata context, "
                "then validate and execute the resulting read-only SQL."
            )
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_llm_plan_direct_query",
            "toolName": "llm_plan_direct_query",
            "input": {
                "requestPlan": request_plan.model_dump(),
                "selectedSources": request_plan.selected_sources,
            },
        },
    )

    direct_plan = await plan_direct_query_with_llm(
        user_question=prompt,
        request_plan=request_plan,
        metadata_context=metadata_context,
        previous_user_answers=previous_user_answers or [],
        run_id=run_id,
    )

    await event_emitter.emit(
        run_id,
        "tool_completed",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_llm_plan_direct_query",
            "toolName": "llm_plan_direct_query",
            "output": {
                "sql": direct_plan.sql,
                "businessInterpretation": direct_plan.business_interpretation,
                "assumptions": direct_plan.assumptions,
                "warnings": direct_plan.warnings,
            },
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_execute_direct_analytics_sql",
            "toolName": "execute_direct_analytics_sql",
            "input": {"sql": direct_plan.sql},
        },
    )

    execution_timer = log_step_start(run_id, "6A", "Execute validated direct SQL", {"sql_preview": direct_plan.sql[:800]})
    try:
        rows = fetch_all(direct_plan.sql)
        log_step_success(run_id, "6A", "Execute validated direct SQL", started_at=execution_timer, details={"row_count": len(rows), "preview_rows": rows[:5]})
    except Exception as exc:
        log_step_failure(run_id, "6A", "Execute validated direct SQL", started_at=execution_timer, error=exc, details={"sql_preview": direct_plan.sql[:1200]})
        raise

    await event_emitter.emit(
        run_id,
        "tool_completed",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_execute_direct_analytics_sql",
            "toolName": "execute_direct_analytics_sql",
            "output": {"rowCount": len(rows), "previewRows": rows[:10]},
        },
    )

    semantic_artifact = {
        "prompt": prompt,
        "request_plan": request_plan.model_dump(),
        "direct_query_plan": direct_plan.model_dump(),
    }
    semantic_plan_json = json.dumps(semantic_artifact, ensure_ascii=False, indent=2, default=str)
    result_json = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
    answer_markdown = _format_direct_answer_markdown(prompt, request_plan, direct_plan, rows)

    artifact_timer = log_step_start(run_id, "7A", "Return direct answer and analytics artifacts", {"row_count": len(rows)})

    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "semantic_query_plan.json", semantic_plan_json, "json")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_query.sql", direct_plan.sql, "sql")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_result.json", result_json, "json")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_answer.md", answer_markdown, "markdown")

    chat_answer = _format_chat_answer(request_plan, direct_plan, rows)

    await event_emitter.emit(
        run_id,
        "agent_response",
        ANALYTICS_AGENT,
        {"text": chat_answer},
    )
    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        ANALYTICS_AGENT,
        {"status": "completed", "summary": "Direct analytics answer completed."},
    )

    log_step_success(run_id, "7A", "Return direct answer and analytics artifacts", started_at=artifact_timer, details={"artifacts": ["semantic_query_plan.json", "analytics_query.sql", "analytics_result.json", "analytics_answer.md"], "chat_answer_preview": chat_answer[:500]})
    log_step_success(run_id, "5A", "Direct Analytics Flow", started_at=flow_timer, details={"row_count": len(rows)})

    return {
        "semantic_plan": semantic_artifact,
        "sql": direct_plan.sql,
        "rows": rows,
        "chat_answer": chat_answer,
        "answer_markdown": answer_markdown,
    }


def _format_chat_answer(request_plan: RequestPlan, direct_plan, rows: list[dict[str, Any]]) -> str:
    if not rows:
        base = "No matching rows were found for the validated query."
    elif len(rows) <= 5:
        base = _rows_to_business_text(rows)
    else:
        base = f"The query returned {len(rows)} rows. See analytics_result.json for the full table. Preview: {_rows_to_business_text(rows[:5])}"

    interpretation = direct_plan.business_interpretation or request_plan.business_interpretation
    parts = []
    if interpretation:
        parts.append(interpretation)
    parts.append(base)
    if direct_plan.warnings:
        parts.append("Warnings: " + "; ".join(direct_plan.warnings))
    parts.append("I saved the SQL, result rows, semantic plan, and full explanation as artifacts.")
    return "\n\n".join(parts)


def _format_direct_answer_markdown(prompt: str, request_plan: RequestPlan, direct_plan, rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Direct Analytics Answer",
        "",
        f"**Question:** {prompt}",
        "",
        "## Business interpretation",
        "",
        direct_plan.business_interpretation or request_plan.business_interpretation or "No business interpretation provided.",
        "",
        "## Result rows",
        "",
        "```json",
        json.dumps(rows, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Assumptions",
        "",
    ]
    assumptions = [*request_plan.assumptions, *direct_plan.assumptions]
    if assumptions:
        lines.extend(f"- {item}" for item in assumptions)
    else:
        lines.append("- No explicit assumptions returned by the planner.")

    if direct_plan.warnings or request_plan.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in [*request_plan.warnings, *direct_plan.warnings])

    lines.extend(["", "## SQL used", "", "```sql", direct_plan.sql, "```", ""])
    return "\n".join(lines).strip() + "\n"


def _rows_to_business_text(rows: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for row in rows:
        label = _row_label(row)
        values = []
        for key, value in row.items():
            if key == label[0]:
                continue
            values.append(f"{key}: {_format_value(value)}")
        if label[1]:
            fragments.append(f"{label[1]} — " + ", ".join(values))
        else:
            fragments.append(", ".join(values))
    return "; ".join(fragments)


def _row_label(row: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in ["customer_name", "customer_id", "customer_segment", "plan_name", "plan_id", "invoice_month", "payment_month", "month", "revenue_month"]:
        if row.get(key) not in {None, ""}:
            return key, str(row[key])
    return None, None


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)

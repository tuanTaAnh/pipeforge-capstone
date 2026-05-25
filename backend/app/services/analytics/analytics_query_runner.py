from __future__ import annotations

import json
from typing import Any

from app.schemas.agents import AgentInfo
from app.services.decisions.answer_queue import answer_queue
from app.services.artifacts.artifact_store import artifact_store
from app.services.database.database_service import fetch_all
from app.services.analytics.direct_answer_formatter import format_chat_answer, format_direct_answer
from app.services.runtime.event_emitter import event_emitter
from app.services.analytics.semantic_query_parser import parse_semantic_query
from app.services.analytics.sql_query_planner import build_sql_query
from app.services.analytics.sql_safety_validator import validate_select_sql


ANALYTICS_AGENT = AgentInfo(
    id="analytics-query-agent",
    name="Analytics Query Agent",
    role="sub_agent",
    parentId="pipeline-architect",
)


async def run_direct_analytics_query(run_id: str, prompt: str) -> dict[str, Any]:
    await event_emitter.emit(run_id, "sub_agent_started", ANALYTICS_AGENT, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        ANALYTICS_AGENT,
        {
            "text": (
                "I will resolve business terms through the semantic mapping layer, "
                "build a safe SQL query, execute it on the demo SQLite database, and return a direct answer."
            )
        },
    )

    semantic_plan = parse_semantic_query(prompt)
    selected_metric = semantic_plan.metric_name

    if semantic_plan.clarification_required and semantic_plan.clarification_question:
        answer_payload = await answer_queue.ask_user_decision(
            run_id=run_id,
            agent=ANALYTICS_AGENT,
            question=semantic_plan.clarification_question,
            validation_error=None,
        )
        selected_metric = answer_payload.get("selectedOptionId") or answer_payload.get("selected_option_id")
        semantic_plan = parse_semantic_query(prompt, forced_metric_name=selected_metric)

    await event_emitter.emit(
        run_id,
        "tool_started",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_plan_direct_analytics_sql",
            "toolName": "plan_direct_analytics_sql",
            "input": semantic_plan.model_dump(),
        },
    )

    sql_plan = build_sql_query(semantic_plan)
    validate_select_sql(sql_plan["sql"])

    await event_emitter.emit(
        run_id,
        "tool_completed",
        ANALYTICS_AGENT,
        {
            "toolCallId": "tool_plan_direct_analytics_sql",
            "toolName": "plan_direct_analytics_sql",
            "output": {
                "metric": semantic_plan.metric_name,
                "dimension": semantic_plan.dimension_name,
                "timePhrase": semantic_plan.time_phrase,
                "sql": sql_plan["sql"],
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
            "input": {"sql": sql_plan["sql"]},
        },
    )

    rows = fetch_all(sql_plan["sql"])

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

    semantic_plan_json = json.dumps(semantic_plan.model_dump(), ensure_ascii=False, indent=2, default=str)
    result_json = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
    answer_markdown = format_direct_answer(prompt, semantic_plan.model_dump(), sql_plan, rows)

    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "semantic_query_plan.json", semantic_plan_json, "json")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_query.sql", sql_plan["sql"], "sql")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_result.json", result_json, "json")
    await artifact_store.write_artifact(run_id, ANALYTICS_AGENT, "analytics_answer.md", answer_markdown, "markdown")

    chat_answer = format_chat_answer(semantic_plan.model_dump(), sql_plan, rows)

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

    return {
        "semantic_plan": semantic_plan.model_dump(),
        "sql_plan": sql_plan,
        "rows": rows,
        "chat_answer": chat_answer,
        "answer_markdown": answer_markdown,
    }

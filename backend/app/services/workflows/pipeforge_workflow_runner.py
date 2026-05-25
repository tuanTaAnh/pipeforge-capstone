from __future__ import annotations

import json
from typing import Any

from app.schemas.agents import AgentInfo
from app.schemas.llm_plans import PlannerQuestion, RequestPlan
from app.services.analytics.analytics_query_runner import run_direct_analytics_query
from app.services.artifacts.artifact_store import artifact_store
from app.services.artifacts.artifact_validator import ArtifactValidationError, validate_generated_artifacts
from app.services.database.multi_source_profiler import profile_sources
from app.services.database.source_profiler import profile_source
from app.services.decisions.answer_queue import answer_queue
from app.services.decisions.answer_validator import validate_answer
from app.services.decisions.business_rule_resolver import (
    build_business_rules_markdown,
    build_business_rules_yaml,
    build_resolved_rule,
)
from app.services.llm.openhands_artifact_generator import (
    generate_doc_artifacts_with_openhands,
    generate_model_artifacts_with_openhands,
    generate_test_artifacts_with_openhands,
)
from app.services.metadata.relationship_validator import validate_relationships
from app.services.metadata.semantic_metadata_loader import get_relationships_for_sources
from app.services.planning.llm_artifact_planner import plan_artifacts_with_llm
from app.services.planning.llm_business_decision_planner import compact_profile_context_for_business_decisions, plan_business_decisions_with_llm
from app.services.planning.llm_request_planner import plan_request_with_llm
from app.services.planning.metadata_context_builder import build_metadata_context, load_selected_contracts
from app.services.runtime.event_emitter import event_emitter
from app.services.runtime.flow_logger import flow_log, log_step_failure, log_step_start, log_step_success, summarize_text
from app.services.runtime.run_registry import registry
from app.services.validation.validation_context import ValidationContext, build_validation_context_from_contracts


PIPELINE_ARCHITECT = AgentInfo(
    id="pipeline-architect",
    name="Pipeline Architect",
    role="orchestrator",
    parentId=None,
)


def sub_agent(agent_id: str, name: str) -> AgentInfo:
    return AgentInfo(id=agent_id, name=name, role="sub_agent", parentId="pipeline-architect")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def _complete_run(run_id: str, final_text: str, *, agent_response: str | None = None) -> None:
    if agent_response:
        await event_emitter.emit(run_id, "agent_response", PIPELINE_ARCHITECT, {"text": agent_response})

    await event_emitter.emit(run_id, "final_message", PIPELINE_ARCHITECT, {"text": final_text})
    await event_emitter.emit(run_id, "agent_completed", PIPELINE_ARCHITECT, {"status": "completed"})
    registry.set_status(run_id, "completed")
    await event_emitter.emit(run_id, "done", PIPELINE_ARCHITECT, {"status": "completed"})


async def _request_plan_with_clarification_loop(
    *,
    run_id: str,
    prompt: str,
    metadata_context: dict[str, Any],
) -> tuple[RequestPlan, list[dict[str, Any]]]:
    previous_answers: list[dict[str, Any]] = []

    for attempt in range(4):
        await event_emitter.emit(
            run_id,
            "tool_started",
            PIPELINE_ARCHITECT,
            {
                "toolCallId": f"tool_llm_request_planner_{attempt + 1}",
                "toolName": "llm_request_planner",
                "input": {"prompt": prompt, "previousAnswers": previous_answers},
            },
        )

        request_plan = await plan_request_with_llm(
            user_question=prompt,
            metadata_context=metadata_context,
            previous_user_answers=previous_answers,
            run_id=run_id,
        )
        registry.runs[run_id]["requestPlan"] = request_plan.model_dump()

        await event_emitter.emit(
            run_id,
            "tool_completed",
            PIPELINE_ARCHITECT,
            {
                "toolCallId": f"tool_llm_request_planner_{attempt + 1}",
                "toolName": "llm_request_planner",
                "output": request_plan.model_dump(),
            },
        )

        if not request_plan.clarification_required:
            return request_plan, previous_answers

        if not request_plan.clarification_question:
            raise RuntimeError("LLM planner requested clarification but did not provide a question.")

        question_dict = _planner_question_to_answer_queue_dict(request_plan.clarification_question)
        step4_timer = log_step_start(run_id, "4", "Ask user if clarification is needed", {"question": question_dict})
        answer_payload = await answer_queue.ask_user_decision(
            run_id=run_id,
            agent=PIPELINE_ARCHITECT,
            question=question_dict,
            validation_error=None,
        )
        log_step_success(run_id, "4", "Ask user if clarification is needed", started_at=step4_timer, details={"answer": answer_payload})
        previous_answers.append(answer_payload)

    raise RuntimeError("Request planning could not resolve the request after multiple clarifications.")


def _planner_question_to_answer_queue_dict(question: PlannerQuestion) -> dict[str, Any]:
    options = []
    for option in question.options:
        resolved_rule = option.resolved_rule or option.description or option.label
        implementation = option.implementation or resolved_rule
        options.append(
            {
                "id": option.id,
                "label": option.label,
                "resolved_rule": resolved_rule,
                "implementation": implementation,
            }
        )

    return {
        "id": question.id,
        "question": question.question,
        "issue_summary": question.issue_summary,
        "priority": question.priority,
        "recommended_option_id": question.recommended_option_id or (options[0]["id"] if options else None),
        "recommendation_reason": question.recommendation_reason,
        "options": options,
        "allow_custom_answer": question.allow_custom_answer,
    }


async def source_inspector(run_id: str, source_name: str) -> dict[str, Any]:
    step_timer = log_step_start(run_id, "6B", "Source Inspector profiles real data", {"sources": [source_name]})
    agent = sub_agent("source-inspector", "Source Inspector")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {"text": f"I will profile the live SQLite source `{source_name}` using code/tools, not LLM guesses."},
    )
    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {"toolCallId": "tool_profile_data", "toolName": "profile_data", "input": {"source": source_name}},
    )

    profile = profile_source(source_name)
    registry.runs[run_id]["sourceProfile"] = profile

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_profile_data",
            "toolName": "profile_data",
            "output": {
                "source": profile["source"],
                "rowCount": profile["row_count"],
                "columns": [column["name"] for column in profile["columns"]],
                "qualityFindings": [
                    {
                        "id": finding.get("id"),
                        "severity": finding.get("severity"),
                        "message": finding.get("message"),
                    }
                    for finding in profile.get("quality_findings", [])
                ],
            },
        },
    )

    await artifact_store.write_artifact(run_id, agent, "source_profile.md", profile["source_profile_markdown"], "markdown")
    await artifact_store.write_artifact(run_id, agent, "data_quality_report.md", profile["data_quality_report_markdown"], "markdown")

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {"status": "completed", "summary": f"Source inspection completed for `{source_name}`."},
    )
    log_step_success(run_id, "6B", "Source Inspector profiles real data", started_at=step_timer, details={"source": source_name, "row_count": profile.get("row_count"), "column_count": len(profile.get("columns", [])), "quality_finding_count": len(profile.get("quality_findings", []))})
    return profile


async def selected_sources_inspector(run_id: str, selected_sources: list[str]) -> dict[str, Any]:
    step_timer = log_step_start(run_id, "6B", "Source Inspector profiles real data", {"sources": selected_sources})
    if len(selected_sources) == 1:
        profile = await source_inspector(run_id, selected_sources[0])
        inspection = {
            "selected_sources": selected_sources,
            "source_profile_context": profile["source_profile_context"],
            "source_profiles": {selected_sources[0]: profile},
            "relationship_results": None,
        }
        log_step_success(run_id, "6B", "Source Inspector profiles real data", started_at=step_timer, details={"sources": selected_sources, "relationship_count": 0})
        return inspection

    agent = sub_agent("source-inspector", "Source Inspector")
    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {"text": "I will profile the selected sources and validate available relationships using code/tools."},
    )
    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {"toolCallId": "tool_profile_selected_sources", "toolName": "profile_selected_sources", "input": {"sources": selected_sources}},
    )

    source_profiles = profile_sources(selected_sources)
    relationships = get_relationships_for_sources(selected_sources)
    relationship_results = validate_relationships(relationships) if relationships else None

    context_parts = [source_profiles["source_profile_context"]]
    if relationship_results:
        context_parts.append("# Relationship Validation JSON\n\n```json\n" + relationship_results["relationship_context"] + "\n```")

    inspection = {
        "selected_sources": selected_sources,
        "source_profiles": source_profiles,
        "relationship_results": relationship_results,
        "source_profile_context": "\n\n".join(context_parts),
    }
    registry.runs[run_id]["sourceProfile"] = inspection

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_profile_selected_sources",
            "toolName": "profile_selected_sources",
            "output": {
                "sources": selected_sources,
                "relationshipCount": len(relationships),
                "relationshipFindings": (relationship_results or {}).get("findings", []),
            },
        },
    )

    await artifact_store.write_artifact(run_id, agent, "source_profile.md", source_profiles["source_profile_markdown"], "markdown")
    await artifact_store.write_artifact(run_id, agent, "data_quality_report.md", source_profiles["data_quality_report_markdown"], "markdown")

    if relationship_results:
        await artifact_store.write_artifact(run_id, agent, "relationship_profile.md", relationship_results["relationship_profile_markdown"], "markdown")
        await artifact_store.write_artifact(run_id, agent, "join_quality_report.md", relationship_results["join_quality_report_markdown"], "markdown")

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {"status": "completed", "summary": "Selected source inspection completed."},
    )
    log_step_success(run_id, "6B", "Source Inspector profiles real data", started_at=step_timer, details={"sources": selected_sources, "relationship_count": len(relationships), "relationship_finding_count": len((relationship_results or {}).get("findings", [])), "profile_context": summarize_text(inspection.get("source_profile_context", ""), max_chars=1200)})
    return inspection


async def resolve_llm_business_questions(
    *,
    run_id: str,
    prompt: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    profiling_context: str,
    previous_user_answers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, str]:
    step7_timer = log_step_start(run_id, "7B", "LLM decides business questions", {"selected_sources": request_plan.selected_sources, "previous_answer_count": len(previous_user_answers), "profiling_context": summarize_text(profiling_context, max_chars=1200)})
    await event_emitter.emit(
        run_id,
        "tool_started",
        PIPELINE_ARCHITECT,
        {
            "toolCallId": "tool_llm_business_decision_planner",
            "toolName": "llm_business_decision_planner",
            "input": {"selectedSources": request_plan.selected_sources},
        },
    )
    decision_plan = await plan_business_decisions_with_llm(
        user_question=prompt,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=profiling_context,
        previous_user_answers=previous_user_answers,
        run_id=run_id,
    )
    questions = [_planner_question_to_answer_queue_dict(question) for question in decision_plan.questions]
    registry.runs[run_id]["plannedQuestions"] = questions
    registry.runs[run_id]["currentQuestionIndex"] = 0

    await event_emitter.emit(
        run_id,
        "tool_completed",
        PIPELINE_ARCHITECT,
        {
            "toolCallId": "tool_llm_business_decision_planner",
            "toolName": "llm_business_decision_planner",
            "output": decision_plan.model_dump(),
        },
    )
    log_step_success(run_id, "7B", "LLM decides business questions", started_at=step7_timer, details={"clarification_required": decision_plan.clarification_required, "question_count": len(decision_plan.questions), "assumptions": decision_plan.assumptions, "warnings": decision_plan.warnings})

    if not questions:
        existing_rules = _previous_answers_to_resolved_rules(previous_user_answers)
        business_rules_yaml = _build_business_rules_yaml_with_planner_notes(existing_rules, decision_plan.assumptions, decision_plan.warnings)
        business_rules_markdown = _build_business_rules_markdown_with_planner_notes(existing_rules, decision_plan.assumptions, decision_plan.warnings)
        await artifact_store.write_artifact(run_id, PIPELINE_ARCHITECT, "business_rules.yml", business_rules_yaml, "yaml")
        await artifact_store.write_artifact(run_id, PIPELINE_ARCHITECT, "business_rules.md", business_rules_markdown, "markdown")
        return existing_rules, business_rules_yaml, business_rules_markdown

    resolved_rules: list[dict[str, Any]] = []
    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {"text": f"I found {len(questions)} business decision question(s) that must be resolved before generating artifacts."},
    )

    for index, question in enumerate(questions):
        registry.runs[run_id]["currentQuestionIndex"] = index
        validation_error: str | None = None
        while True:
            answer_payload = await answer_queue.ask_user_decision(
                run_id=run_id,
                agent=PIPELINE_ARCHITECT,
                question=question,
                validation_error=validation_error,
            )
            validation = validate_answer(question, answer_payload)
            if validation["is_valid"]:
                resolved_rule = build_resolved_rule(question, validation)
                resolved_rules.append(resolved_rule)
                registry.runs[run_id]["resolvedRules"] = resolved_rules
                previous_user_answers.append(answer_payload)
                await event_emitter.emit(
                    run_id,
                    "agent_response",
                    PIPELINE_ARCHITECT,
                    {"text": f"Decision recorded:\n{resolved_rule['decision']}\n\nImplementation hint: {resolved_rule['implementation']}"},
                )
                break
            validation_error = validation["message"]

    business_rules_yaml = build_business_rules_yaml(resolved_rules)
    business_rules_markdown = build_business_rules_markdown(resolved_rules)
    await artifact_store.write_artifact(run_id, PIPELINE_ARCHITECT, "business_rules.yml", business_rules_yaml, "yaml")
    await artifact_store.write_artifact(run_id, PIPELINE_ARCHITECT, "business_rules.md", business_rules_markdown, "markdown")
    return resolved_rules, business_rules_yaml, business_rules_markdown


def _previous_answers_to_resolved_rules(previous_user_answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved_rules: list[dict[str, Any]] = []

    for answer in previous_user_answers:
        question_id = str(answer.get("questionId") or answer.get("question_id") or "previous_user_decision")
        raw_answer = str(answer.get("answer") or answer.get("customAnswer") or answer.get("selectedOptionId") or "").strip()
        selected_option_id = answer.get("selectedOptionId") or answer.get("selected_option_id")

        if not raw_answer and not selected_option_id:
            continue

        decision = raw_answer or str(selected_option_id)
        implementation = decision

        resolved_rules.append(
            {
                "question_id": question_id,
                "issue_id": question_id,
                "issue_summary": "User-provided business decision collected before artifact planning.",
                "question": "Planner clarification / business decision.",
                "answer_type": "previous_user_answer",
                "raw_answer": raw_answer,
                "selected_option_id": selected_option_id,
                "decision": decision,
                "implementation": implementation,
                "source": "previous_user_answer",
            }
        )

    return resolved_rules


def _build_business_rules_yaml_with_planner_notes(
    resolved_rules: list[dict[str, Any]],
    assumptions: list[str],
    warnings: list[str],
) -> str:
    base_yaml = build_business_rules_yaml(resolved_rules).rstrip()
    lines = [base_yaml]

    if assumptions:
        lines.append("assumptions:")
        for assumption in assumptions:
            lines.append(f"  - {_yaml_quote(assumption)}")

    if warnings:
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"  - {_yaml_quote(warning)}")

    return "\n".join(lines).strip() + "\n"


def _build_business_rules_markdown_with_planner_notes(
    resolved_rules: list[dict[str, Any]],
    assumptions: list[str],
    warnings: list[str],
) -> str:
    content = build_business_rules_markdown(resolved_rules).rstrip()
    lines = [content]

    if assumptions:
        lines.extend(["", "## Planner Assumptions", ""])
        for assumption in assumptions:
            lines.append(f"- {assumption}")

    if warnings:
        lines.extend(["", "## Planner Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines).strip() + "\n"


def _yaml_quote(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


async def model_builder(run_id: str, source_profile_context: str, business_rules_context: str, artifact_plan: dict[str, Any], validation_context: ValidationContext) -> list[dict[str, Any]]:
    agent = sub_agent("model-builder", "Model Builder")
    target_files = artifact_plan.get("model_files", [])
    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(run_id, "agent_thinking", agent, {"text": "I will use OpenHands SDK to generate the SQL model files from the LLM artifact plan."})
    await event_emitter.emit(run_id, "tool_started", agent, {"toolCallId": "tool_openhands_generate_models", "toolName": "openhands_generate_model_artifacts", "input": {"targetFiles": target_files}})
    artifacts = await generate_model_artifacts_with_openhands(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context=validation_context)
    await event_emitter.emit(run_id, "tool_completed", agent, {"toolCallId": "tool_openhands_generate_models", "toolName": "openhands_generate_model_artifacts", "output": {"createdFiles": [artifact["filename"] for artifact in artifacts]}})
    for artifact in artifacts:
        await artifact_store.write_artifact(run_id, agent, artifact["filename"], artifact["content"], artifact["type"])
    await event_emitter.emit(run_id, "sub_agent_completed", agent, {"status": "completed", "summary": "Generated SQL model artifacts."})
    return list(artifacts)


async def test_writer(run_id: str, source_profile_context: str, business_rules_context: str, artifact_plan: dict[str, Any], validation_context: ValidationContext) -> list[dict[str, Any]]:
    agent = sub_agent("test-writer", "Test Writer")
    target_files = artifact_plan.get("test_files", [])
    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(run_id, "agent_thinking", agent, {"text": "I will use OpenHands SDK to generate schema and custom test artifacts."})
    await event_emitter.emit(run_id, "tool_started", agent, {"toolCallId": "tool_openhands_generate_tests", "toolName": "openhands_generate_test_artifacts", "input": {"targetFiles": target_files}})
    artifacts = await generate_test_artifacts_with_openhands(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context=validation_context)
    await event_emitter.emit(run_id, "tool_completed", agent, {"toolCallId": "tool_openhands_generate_tests", "toolName": "openhands_generate_test_artifacts", "output": {"createdFiles": [artifact["filename"] for artifact in artifacts]}})
    for artifact in artifacts:
        await artifact_store.write_artifact(run_id, agent, artifact["filename"], artifact["content"], artifact["type"])
    await event_emitter.emit(run_id, "sub_agent_completed", agent, {"status": "completed", "summary": "Generated test artifacts."})
    return list(artifacts)


async def doc_writer(run_id: str, source_profile_context: str, business_rules_context: str, artifact_plan: dict[str, Any], validation_context: ValidationContext) -> list[dict[str, Any]]:
    agent = sub_agent("doc-writer", "Documentation Writer")
    target_files = artifact_plan.get("documentation_files", [])
    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(run_id, "agent_thinking", agent, {"text": "I will use OpenHands SDK to generate documentation and the pipeline summary."})
    await event_emitter.emit(run_id, "tool_started", agent, {"toolCallId": "tool_openhands_generate_docs", "toolName": "openhands_generate_documentation_artifacts", "input": {"targetFiles": target_files}})
    artifacts = await generate_doc_artifacts_with_openhands(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context=validation_context)
    await event_emitter.emit(run_id, "tool_completed", agent, {"toolCallId": "tool_openhands_generate_docs", "toolName": "openhands_generate_documentation_artifacts", "output": {"createdFiles": [artifact["filename"] for artifact in artifacts]}})
    for artifact in artifacts:
        await artifact_store.write_artifact(run_id, agent, artifact["filename"], artifact["content"], artifact["type"])
    await event_emitter.emit(run_id, "sub_agent_completed", agent, {"status": "completed", "summary": "Generated documentation artifacts."})
    return list(artifacts)


async def generate_artifacts_in_review_order(run_id: str, source_profile_context: str, business_rules_context: str, artifact_plan: dict[str, Any], validation_context: ValidationContext) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    artifacts.extend(await model_builder(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context))
    artifacts.extend(await test_writer(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context))
    artifacts.extend(await doc_writer(run_id, source_profile_context, business_rules_context, artifact_plan, validation_context))
    return artifacts


async def run_data_product_generation(
    *,
    run_id: str,
    prompt: str,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
) -> None:
    selected_sources = request_plan.selected_sources
    if not selected_sources:
        raise RuntimeError("Data product generation requires selected sources.")

    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {"text": f"I will build a data product from the LLM-selected sources: {', '.join(selected_sources)}."},
    )

    step5b_timer = log_step_start(run_id, "5B", "Load detailed selected contracts", {"selected_sources": selected_sources})
    await event_emitter.emit(
        run_id,
        "tool_started",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_load_selected_contracts", "toolName": "load_selected_contracts", "input": {"sources": selected_sources}},
    )
    selected_contracts = load_selected_contracts(selected_sources)
    await event_emitter.emit(
        run_id,
        "tool_completed",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_load_selected_contracts", "toolName": "load_selected_contracts", "output": {"loadedSources": list(selected_contracts.keys())}},
    )
    log_step_success(run_id, "5B", "Load detailed selected contracts", started_at=step5b_timer, details={"loaded_sources": list(selected_contracts.keys())})

    inspection = await selected_sources_inspector(run_id, selected_sources)
    profiling_context = inspection["source_profile_context"]

    _, business_rules_yaml, _ = await resolve_llm_business_questions(
        run_id=run_id,
        prompt=prompt,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=profiling_context,
        previous_user_answers=previous_user_answers,
    )

    generation_profile_context = compact_profile_context_for_business_decisions(
        profiling_context=profiling_context,
        selected_sources=selected_sources,
        previous_user_answers=previous_user_answers,
    )
    flow_log(
        run_id=run_id,
        step_id="6B",
        step_name="Prepare compact generation profile context",
        event="context_compacted",
        status="completed",
        details={
            "raw_profile_chars": len(profiling_context),
            "generation_profile": summarize_text(generation_profile_context, max_chars=1200),
        },
    )

    step8b_timer = log_step_start(run_id, "8B", "LLM creates artifact_plan.json", {"selected_sources": selected_sources, "business_rules_chars": len(business_rules_yaml), "profiling_context": summarize_text(generation_profile_context, max_chars=1200)})
    await event_emitter.emit(
        run_id,
        "tool_started",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_llm_artifact_planner", "toolName": "llm_artifact_planner", "input": {"selectedSources": selected_sources}},
    )
    artifact_plan_model = await plan_artifacts_with_llm(
        user_question=prompt,
        request_plan=request_plan,
        metadata_context=metadata_context,
        profiling_context=generation_profile_context,
        business_rules_context=business_rules_yaml,
        previous_user_answers=previous_user_answers,
        run_id=run_id,
    )
    artifact_plan = artifact_plan_model.as_artifact_plan_dict()
    registry.runs[run_id]["artifactPlan"] = artifact_plan
    await event_emitter.emit(
        run_id,
        "tool_completed",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_llm_artifact_planner", "toolName": "llm_artifact_planner", "output": artifact_plan},
    )
    await artifact_store.write_artifact(run_id, PIPELINE_ARCHITECT, "artifact_plan.json", _json_dumps(artifact_plan), "json")
    validation_context = build_validation_context_from_contracts(selected_contracts=selected_contracts, artifact_plan=artifact_plan)
    registry.runs[run_id]["validationContext"] = validation_context.to_dict()
    log_step_success(
        run_id,
        "8B",
        "LLM creates artifact_plan.json",
        started_at=step8b_timer,
        details={
            "artifact_plan": artifact_plan,
            "validation_context": validation_context.to_dict(),
        },
    )

    step9b_timer = log_step_start(run_id, "9B", "Dispatch model/test/doc agents", {"model_files": artifact_plan.get("model_files", []), "test_files": artifact_plan.get("test_files", []), "documentation_files": artifact_plan.get("documentation_files", []), "allowed_source_refs": validation_context.allowed_source_refs})
    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {"text": "The artifact plan is ready. I will dispatch model, test, and documentation agents."},
    )
    log_step_success(run_id, "9B", "Dispatch model/test/doc agents", started_at=step9b_timer, details={"agents": ["model-builder", "test-writer", "doc-writer"]})

    step10b_timer = log_step_start(run_id, "10B", "Agents generate artifacts", {"artifact_plan": artifact_plan})
    artifacts = await generate_artifacts_in_review_order(
        run_id=run_id,
        source_profile_context=generation_profile_context,
        business_rules_context=business_rules_yaml,
        artifact_plan=artifact_plan,
        validation_context=validation_context,
    )

    log_step_success(run_id, "10B", "Agents generate artifacts", started_at=step10b_timer, details={"artifact_count": len(artifacts), "created_files": [artifact.get("filename") for artifact in artifacts]})

    step11b_timer = log_step_start(run_id, "11B", "Code validates artifacts", {"artifact_count": len(artifacts), "artifact_plan": artifact_plan})
    await event_emitter.emit(
        run_id,
        "tool_started",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_validate_generated_artifacts", "toolName": "validate_generated_artifacts", "input": {"artifactPlan": artifact_plan}},
    )
    try:
        validation_result = validate_generated_artifacts(
            artifacts=artifacts,
            artifact_plan=artifact_plan,
            validation_context=validation_context,
        )
    except ArtifactValidationError as exc:
        validation_result = {"valid": False, "errors": exc.errors}
        log_step_failure(run_id, "11B", "Code validates artifacts", started_at=step11b_timer, error=exc, details=validation_result)
        flow_log(run_id=run_id, step_id="12B", step_name="LLM repairs failed artifacts only", event="not_completed", status="failed", details={"reason": "Deep artifact validation failed after OpenHands internal repair attempts.", "errors": exc.errors})
        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {"text": "Artifact validation found issues after targeted repair attempts: " + "; ".join(exc.errors)},
        )
        raise

    await event_emitter.emit(
        run_id,
        "tool_completed",
        PIPELINE_ARCHITECT,
        {"toolCallId": "tool_validate_generated_artifacts", "toolName": "validate_generated_artifacts", "output": validation_result},
    )
    log_step_success(run_id, "11B", "Code validates artifacts", started_at=step11b_timer, details=validation_result)
    flow_log(run_id=run_id, step_id="12B", step_name="LLM repairs failed artifacts only", event="not_needed", status="completed", details={"reason": "Artifacts passed validation; no targeted repair was required."})

    package_name = artifact_plan.get("package_name", "PipeForge Data Product Draft")
    final_mart = artifact_plan.get("final_mart_name", "configured final mart")
    final_text = f"""Your {package_name} is ready for analytics review.

Sources:
{', '.join(selected_sources)}

Final mart:
{final_mart}

Generated package:
- Source profile and data quality report
- Resolved business rules
- artifact_plan.json
- dbt model files: {', '.join(artifact_plan.get('model_files', []))}
- dbt test files: {', '.join(artifact_plan.get('test_files', []))}
- Documentation files: {', '.join(artifact_plan.get('documentation_files', []))}

Recommended next steps:
1. Review source_profile.md, data_quality_report.md, business_rules.yml, and artifact_plan.json.
2. Review the generated SQL/YAML/Markdown artifacts.
3. Open the Pipeline tab and run the generated models manually into the demo data mart.
4. Preview/download generated output tables.
"""
    step13b_timer = log_step_start(run_id, "13B", "Return final artifacts", {"package_name": package_name, "final_mart": final_mart, "selected_sources": selected_sources})
    await _complete_run(run_id, final_text)
    log_step_success(run_id, "13B", "Return final artifacts", started_at=step13b_timer, details={"status": "completed"})


async def run_pipeforge_workflow(run_id: str, prompt: str) -> None:
    try:
        registry.set_status(run_id, "running")
        await event_emitter.emit(run_id, "session_started", PIPELINE_ARCHITECT, {"prompt": prompt})
        await event_emitter.emit(run_id, "agent_started", PIPELINE_ARCHITECT, {"status": "running"})
        await event_emitter.emit(
            run_id,
            "agent_thinking",
            PIPELINE_ARCHITECT,
            {
                "text": (
                    "I will load metadata context, ask an LLM planner to classify the request, "
                    "validate the structured plan, ask the user if needed, then route to direct analytics or data product generation."
                )
            },
        )

        step1_timer = log_step_start(run_id, "1", "Load metadata context", {"prompt": prompt})
        await event_emitter.emit(
            run_id,
            "tool_started",
            PIPELINE_ARCHITECT,
            {"toolCallId": "tool_load_metadata_context", "toolName": "load_metadata_context", "input": {}},
        )
        metadata_context = build_metadata_context()
        registry.runs[run_id]["metadataContext"] = {
            "allowed_sources": metadata_context.get("allowed_sources"),
            "allowed_metrics": metadata_context.get("allowed_metrics"),
            "allowed_data_products": metadata_context.get("allowed_data_products"),
        }
        await event_emitter.emit(
            run_id,
            "tool_completed",
            PIPELINE_ARCHITECT,
            {
                "toolCallId": "tool_load_metadata_context",
                "toolName": "load_metadata_context",
                "output": registry.runs[run_id]["metadataContext"],
            },
        )
        log_step_success(run_id, "1", "Load metadata context", started_at=step1_timer, details=registry.runs[run_id]["metadataContext"])

        request_plan, previous_answers = await _request_plan_with_clarification_loop(
            run_id=run_id,
            prompt=prompt,
            metadata_context=metadata_context,
        )

        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {
                "text": (
                    f"Planner route: `{request_plan.request_type}`.\n"
                    f"Business interpretation: {request_plan.business_interpretation or 'n/a'}\n"
                    f"Selected sources: {', '.join(request_plan.selected_sources) or 'n/a'}"
                )
            },
        )

        flow_log(run_id=run_id, step_id="2/3", step_name="Request planning route selected", event="route_selected", status="completed", details={"request_plan": request_plan.model_dump(), "previous_answer_count": len(previous_answers)})

        if request_plan.request_type == "out_of_scope":
            await _complete_run(
                run_id,
                "This request is outside the current PipeForge data/product domain. Please ask about the available analytics sources, metrics, or data product generation workflow.",
                agent_response=request_plan.business_interpretation or "The LLM planner classified the request as out of scope.",
            )
            return

        if request_plan.request_type == "clarification":
            await _complete_run(
                run_id,
                request_plan.business_interpretation or "I need more detail before I can proceed.",
            )
            return

        if request_plan.request_type == "direct_analytics":
            result = await run_direct_analytics_query(
                run_id=run_id,
                prompt=prompt,
                request_plan=request_plan,
                metadata_context=metadata_context,
                previous_user_answers=previous_answers,
            )
            await _complete_run(run_id, result["chat_answer"])
            return

        if request_plan.request_type == "data_product_generation":
            await run_data_product_generation(
                run_id=run_id,
                prompt=prompt,
                request_plan=request_plan,
                metadata_context=metadata_context,
                previous_user_answers=previous_answers,
            )
            return

        raise RuntimeError(f"Unsupported request_type: {request_plan.request_type}")

    except Exception as exc:
        log_step_failure(run_id, "FLOW", "PipeForge backend flow", error=exc, details={"prompt": prompt})
        registry.set_status(run_id, "failed")
        await event_emitter.emit(run_id, "error", PIPELINE_ARCHITECT, {"message": str(exc)})
        await event_emitter.emit(run_id, "agent_failed", PIPELINE_ARCHITECT, {"status": "failed", "message": str(exc)})
        await event_emitter.emit(run_id, "done", PIPELINE_ARCHITECT, {"status": "failed"})

import asyncio
from typing import Any

from app.core.config import settings
from app.schemas.agents import AgentInfo
from app.services.decisions.answer_queue import answer_queue
from app.services.decisions.answer_validator import validate_answer
from app.services.analytics.analytics_query_runner import run_direct_analytics_query
from app.services.artifacts.artifact_store import artifact_store
from app.services.decisions.business_rule_resolver import (
    build_business_rules_markdown,
    build_business_rules_yaml,
    build_resolved_rule,
)
from app.services.metadata.data_product_selector import select_data_product_for_prompt
from app.services.runtime.event_emitter import event_emitter
from app.services.analytics.direct_query_classifier import classify_direct_analytics_query
from app.services.metadata.domain_relevance_classifier import classify_domain_relevance
from app.services.metadata.join_planner import build_join_plan, build_join_plan_context, render_join_plan_markdown
from app.services.llm.llm_intent_classifier import (
    classify_intent_with_llm,
    merge_domain_and_llm_classification,
)
from app.services.database.multi_source_profiler import profile_sources
from app.services.metadata.relationship_validator import validate_relationships
from app.services.metadata.request_classifier import classify_request_scope
from app.services.metadata.semantic_metadata_loader import (
    get_data_product_artifact_plan,
    get_relationship_by_id,
)
from app.services.llm.openhands_artifact_generator import (
    generate_doc_artifacts_with_openhands,
    generate_model_artifacts_with_openhands,
    generate_test_artifacts_with_openhands,
)
from app.services.decisions.question_planner import plan_questions
from app.services.runtime.run_registry import registry
from app.services.database.source_profiler import profile_source
from app.services.metadata.source_selector import select_source_for_prompt


PIPELINE_ARCHITECT = AgentInfo(
    id="pipeline-architect",
    name="Pipeline Architect",
    role="orchestrator",
    parentId=None,
)


def _routing_from_domain_classification(domain_classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "deterministic",
        "relevance": domain_classification.get("relevance", "ambiguous_database_request"),
        "intent": "clarification_needed"
        if domain_classification.get("should_ask_clarification")
        else "direct_or_generation_unknown",
        "confidence": float(domain_classification.get("confidence", 0.0)),
        "reason": domain_classification.get("reason", ""),
        "mapped_terms": {},
        "needs_clarification": bool(domain_classification.get("should_ask_clarification", False)),
        "clarifying_question": domain_classification.get("message", ""),
        "suggested_options": [],
        "used_llm": False,
        "error": None,
    }


async def _complete_run_with_message(
    run_id: str,
    message: str,
    agent_response: str | None = None,
) -> None:
    if agent_response:
        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {"text": agent_response},
        )

    await event_emitter.emit(
        run_id,
        "final_message",
        PIPELINE_ARCHITECT,
        {"text": message},
    )
    await event_emitter.emit(
        run_id,
        "agent_completed",
        PIPELINE_ARCHITECT,
        {"status": "completed"},
    )

    registry.set_status(run_id, "completed")

    await event_emitter.emit(
        run_id,
        "done",
        PIPELINE_ARCHITECT,
        {"status": "completed"},
    )


def _format_clarification_message(routing_classification: dict[str, Any]) -> str:
    question = (
        routing_classification.get("clarifying_question")
        or "Please specify the metric, dimension, source, or data product you want to analyze."
    )
    options = routing_classification.get("suggested_options") or []

    if not options:
        return str(question)

    option_lines = "\n".join(f"- {option}" for option in options)
    return f"{question}\n\nSuggested options:\n{option_lines}"


def sub_agent(agent_id: str, name: str) -> AgentInfo:
    return AgentInfo(
        id=agent_id,
        name=name,
        role="sub_agent",
        parentId="pipeline-architect",
    )


async def source_inspector(run_id: str, source_name: str) -> dict[str, Any]:
    agent = sub_agent("source-inspector", "Source Inspector")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": (
                f"I will profile the live SQLite source `{source_name}` "
                "and detect contract-aware data quality issues."
            )
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_profile_data",
            "toolName": "profile_data",
            "input": {"source": source_name},
        },
    )

    profile = profile_source(source_name)
    registry.runs[run_id]["sourceProfile"] = profile

    tool_output = {
        "source": profile["source"],
        "rowCount": profile["row_count"],
        "columns": [column["name"] for column in profile["columns"]],
        "artifactPlan": profile.get("artifact_plan", {}),
        "qualityFindings": [
            {
                "id": finding["id"],
                "severity": finding["severity"],
                "message": finding["message"],
                "affects": finding["affects"],
            }
            for finding in profile["quality_findings"]
        ],
    }

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_profile_data",
            "toolName": "profile_data",
            "output": tool_output,
        },
    )

    await artifact_store.write_artifact(
        run_id,
        agent,
        "source_profile.md",
        profile["source_profile_markdown"],
        "markdown",
    )

    await artifact_store.write_artifact(
        run_id,
        agent,
        "data_quality_report.md",
        profile["data_quality_report_markdown"],
        "markdown",
    )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {
            "status": "completed",
            "summary": f"Source inspection completed for `{source_name}`.",
        },
    )

    return profile


async def resolve_business_questions(
    run_id: str,
    profile: dict[str, Any],
    user_request: str,
) -> tuple[list[dict], str, str]:
    questions = await plan_questions(profile=profile, user_request=user_request)

    registry.runs[run_id]["plannedQuestions"] = questions
    registry.runs[run_id]["currentQuestionIndex"] = 0

    if not questions:
        return [], "version: 1\nrules: {}\n", "# Resolved Business Rules\n\nNo business rules were required.\n"

    resolved_rules: list[dict] = []

    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {
            "text": (
                f"I found {len(questions)} business-critical data quality question(s) "
                "that must be resolved before generating the pipeline."
            )
        },
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

                await event_emitter.emit(
                    run_id,
                    "agent_response",
                    PIPELINE_ARCHITECT,
                    {
                        "text": (
                            "Decision recorded:\n"
                            f"{resolved_rule['decision']}\n\n"
                            f"Implementation hint: {resolved_rule['implementation']}"
                        )
                    },
                )

                break

            validation_error = validation["message"]

            await event_emitter.emit(
                run_id,
                "agent_response",
                PIPELINE_ARCHITECT,
                {
                    "text": (
                        f"{validation_error}\n\n"
                        "You can choose one of the predefined suggestions or enter a clearer custom rule."
                    )
                },
            )

    business_rules_yaml = build_business_rules_yaml(resolved_rules)
    business_rules_markdown = build_business_rules_markdown(resolved_rules)

    await artifact_store.write_artifact(
        run_id,
        PIPELINE_ARCHITECT,
        "business_rules.yml",
        business_rules_yaml,
        "yaml",
    )

    await artifact_store.write_artifact(
        run_id,
        PIPELINE_ARCHITECT,
        "business_rules.md",
        business_rules_markdown,
        "markdown",
    )

    return resolved_rules, business_rules_yaml, business_rules_markdown


async def model_builder(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> None:
    agent = sub_agent("model-builder", "Model Builder")
    target_files = artifact_plan.get("model_files", [])

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": (
                "I will use OpenHands SDK to generate dbt SQL models from the "
                "selected source profile, source contract, artifact plan, and resolved business rules."
            )
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_openhands_generate_models",
            "toolName": "openhands_generate_model_artifacts",
            "input": {
                "targetFiles": target_files,
                "sourceProfile": "source_profile.md + data_quality_report.md",
                "businessRules": "business_rules.yml",
                "artifactPlan": artifact_plan,
            },
        },
    )

    artifacts = await generate_model_artifacts_with_openhands(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_openhands_generate_models",
            "toolName": "openhands_generate_model_artifacts",
            "output": {
                "createdFiles": [artifact["filename"] for artifact in artifacts],
                "source": "openhands-sdk",
            },
        },
    )

    for artifact in artifacts:
        await artifact_store.write_artifact(
            run_id,
            agent,
            artifact["filename"],
            artifact["content"],
            artifact["type"],
        )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {
            "status": "completed",
            "summary": "Generated dbt SQL models using OpenHands SDK.",
        },
    )


async def test_writer(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> None:
    agent = sub_agent("test-writer", "Test Writer")
    target_files = artifact_plan.get("test_files", [])

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": (
                "I will use OpenHands SDK to generate dbt schema tests and custom "
                "data quality checks from the selected source contract and resolved rules."
            )
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_openhands_generate_tests",
            "toolName": "openhands_generate_test_artifacts",
            "input": {
                "targetFiles": target_files,
                "sourceProfile": "source_profile.md + data_quality_report.md",
                "businessRules": "business_rules.yml",
                "artifactPlan": artifact_plan,
            },
        },
    )

    artifacts = await generate_test_artifacts_with_openhands(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_openhands_generate_tests",
            "toolName": "openhands_generate_test_artifacts",
            "output": {
                "createdFiles": [artifact["filename"] for artifact in artifacts],
                "source": "openhands-sdk",
            },
        },
    )

    for artifact in artifacts:
        await artifact_store.write_artifact(
            run_id,
            agent,
            artifact["filename"],
            artifact["content"],
            artifact["type"],
        )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {
            "status": "completed",
            "summary": "Generated dbt tests using OpenHands SDK.",
        },
    )


async def doc_writer(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> None:
    agent = sub_agent("doc-writer", "Documentation Writer")
    target_files = artifact_plan.get("documentation_files", [])

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": (
                "I will use OpenHands SDK to document the selected source, data quality findings, "
                "artifact plan, resolved business rules, assumptions, generated models, tests, and next steps."
            )
        },
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_openhands_generate_docs",
            "toolName": "openhands_generate_documentation_artifacts",
            "input": {
                "targetFiles": target_files,
                "sourceProfile": "source_profile.md + data_quality_report.md",
                "businessRules": "business_rules.yml",
                "artifactPlan": artifact_plan,
            },
        },
    )

    artifacts = await generate_doc_artifacts_with_openhands(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_openhands_generate_docs",
            "toolName": "openhands_generate_documentation_artifacts",
            "output": {
                "createdFiles": [artifact["filename"] for artifact in artifacts],
                "source": "openhands-sdk",
            },
        },
    )

    for artifact in artifacts:
        await artifact_store.write_artifact(
            run_id,
            agent,
            artifact["filename"],
            artifact["content"],
            artifact["type"],
        )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {
            "status": "completed",
            "summary": "Generated final documentation using OpenHands SDK.",
        },
    )


async def generate_artifacts_in_review_order(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> None:
    """
    Generate artifacts in a deterministic review order.

    The previous implementation used asyncio.gather(), which made Model Builder,
    Test Writer, and Documentation Writer run in parallel. That allowed
    Documentation Writer to complete before Test Writer, which was confusing in
    the UI and made the workflow look logically incorrect.

    This sequence is intentionally ordered:
    1. Model Builder creates SQL models.
    2. Test Writer creates schema/custom tests after models exist.
    3. Documentation Writer creates final documentation after models and tests.
    """
    await model_builder(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    await test_writer(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    await doc_writer(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )


def build_multi_source_questions(
    data_product_contract: dict[str, Any],
    relationship_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    data_product = data_product_contract.get("data_product", {})
    configured_questions = data_product.get("business_questions", [])

    if not isinstance(configured_questions, list):
        return []

    finding_by_id = {
        str(finding.get("id")): finding
        for finding in relationship_findings
        if isinstance(finding, dict) and finding.get("id")
    }

    finding_type_by_issue_id = {
        str(finding.get("id")): str(finding.get("type"))
        for finding in relationship_findings
        if isinstance(finding, dict) and finding.get("id")
    }

    questions: list[dict[str, Any]] = []

    for configured_question in configured_questions:
        if not isinstance(configured_question, dict):
            continue

        question_id = str(configured_question.get("id", "")).strip()

        if not question_id:
            continue

        issue_id = str(configured_question.get("issue_id") or question_id.replace("q_", "issue_"))
        finding = finding_by_id.get(issue_id)

        issue_summary = str(
            configured_question.get("issue_summary")
            or (finding or {}).get("message")
            or configured_question.get("question")
            or "Multi-source business decision required."
        )

        options = []

        for option in configured_question.get("options", []):
            if not isinstance(option, dict):
                continue

            option_id = str(option.get("id", "")).strip()
            label = str(option.get("label", "")).strip()
            resolved_rule = str(option.get("resolved_rule", "")).strip()
            implementation = str(option.get("implementation", resolved_rule)).strip()

            if option_id and label and resolved_rule and implementation:
                options.append(
                    {
                        "id": option_id,
                        "label": label,
                        "resolved_rule": resolved_rule,
                        "implementation": implementation,
                    }
                )

        if len(options) < 2:
            continue

        questions.append(
            {
                "id": question_id,
                "issue_id": issue_id,
                "priority": configured_question.get("priority", "must_answer"),
                "issue_summary": issue_summary,
                "question": str(configured_question.get("question")),
                "recommended_option_id": str(
                    configured_question.get("recommended_option_id") or options[0]["id"]
                ),
                "recommendation_reason": str(
                    configured_question.get("recommendation_reason")
                    or "This option preserves auditability while keeping the generated model deterministic."
                ),
                "options": options,
                "allow_custom_answer": bool(configured_question.get("allow_custom_answer", True)),
                "finding_type": finding_type_by_issue_id.get(issue_id),
            }
        )

    return questions


async def multi_source_inspector(
    run_id: str,
    prompt: str,
) -> dict[str, Any]:
    agent = sub_agent("multi-source-inspector", "Multi-Source Inspector")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": (
                "I will select the relevant multi-source data product, profile all required tables, "
                "validate the configured relationships, and build an explicit join plan."
            )
        },
    )

    selection = select_data_product_for_prompt(prompt)
    data_product_contract = selection["contract"]
    data_product = selection["data_product"]
    artifact_plan = get_data_product_artifact_plan(data_product_contract)

    registry.runs[run_id]["selectedDataProduct"] = selection

    relationship_definitions = [
        get_relationship_by_id(relationship_id)
        for relationship_id in selection["relationships"]
    ]

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_profile_multi_source_data",
            "toolName": "profile_multi_source_data",
            "input": {
                "dataProduct": selection["data_product_name"],
                "sources": selection["sources"],
                "relationships": selection["relationships"],
            },
        },
    )

    source_profiles = profile_sources(selection["sources"])
    relationship_results = validate_relationships(relationship_definitions)
    join_plan = build_join_plan(
        data_product_contract=data_product_contract,
        relationship_results=relationship_results["relationships"],
    )

    combined_context = "\n\n".join(
        [
            "# Data Product Contract JSON\n\n```json\n"
            + _json_dumps(data_product)
            + "\n```",
            source_profiles["source_profile_context"],
            "# Relationship Validation JSON\n\n```json\n"
            + relationship_results["relationship_context"]
            + "\n```",
            build_join_plan_context(join_plan),
        ]
    )

    inspection = {
        "selection": selection,
        "data_product_contract": data_product_contract,
        "data_product": data_product,
        "artifact_plan": artifact_plan,
        "source_profiles": source_profiles,
        "relationship_results": relationship_results,
        "join_plan": join_plan,
        "source_profile_context": combined_context,
    }

    registry.runs[run_id]["sourceProfile"] = inspection

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_profile_multi_source_data",
            "toolName": "profile_multi_source_data",
            "output": {
                "dataProduct": selection["data_product_name"],
                "sources": selection["sources"],
                "relationships": selection["relationships"],
                "relationshipFindings": [
                    {
                        "id": finding["id"],
                        "severity": finding["severity"],
                        "message": finding["message"],
                    }
                    for finding in relationship_results.get("findings", [])
                ],
                "artifactPlan": artifact_plan,
            },
        },
    )

    await artifact_store.write_artifact(
        run_id,
        agent,
        "source_profile.md",
        source_profiles["source_profile_markdown"],
        "markdown",
    )
    await artifact_store.write_artifact(
        run_id,
        agent,
        "data_quality_report.md",
        source_profiles["data_quality_report_markdown"],
        "markdown",
    )
    await artifact_store.write_artifact(
        run_id,
        agent,
        "relationship_profile.md",
        relationship_results["relationship_profile_markdown"],
        "markdown",
    )
    await artifact_store.write_artifact(
        run_id,
        agent,
        "join_quality_report.md",
        relationship_results["join_quality_report_markdown"],
        "markdown",
    )
    await artifact_store.write_artifact(
        run_id,
        agent,
        "join_plan.md",
        render_join_plan_markdown(join_plan),
        "markdown",
    )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {
            "status": "completed",
            "summary": (
                f"Multi-source inspection completed for `{selection['data_product_name']}`."
            ),
        },
    )

    return inspection


async def resolve_multi_source_business_questions(
    run_id: str,
    inspection: dict[str, Any],
) -> tuple[list[dict], str, str]:
    relationship_findings = inspection["relationship_results"].get("findings", [])
    questions = build_multi_source_questions(
        data_product_contract=inspection["data_product_contract"],
        relationship_findings=relationship_findings,
    )

    registry.runs[run_id]["plannedQuestions"] = questions
    registry.runs[run_id]["currentQuestionIndex"] = 0

    if not questions:
        return [], "version: 1\nrules: {}\n", "# Resolved Business Rules\n\nNo business rules were required.\n"

    resolved_rules: list[dict] = []

    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {
            "text": (
                f"I found {len(questions)} multi-source reconciliation decision(s) "
                "that must be resolved before generating the joined pipeline."
            )
        },
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

                await event_emitter.emit(
                    run_id,
                    "agent_response",
                    PIPELINE_ARCHITECT,
                    {
                        "text": (
                            "Decision recorded:\n"
                            f"{resolved_rule['decision']}\n\n"
                            f"Implementation hint: {resolved_rule['implementation']}"
                        )
                    },
                )

                break

            validation_error = validation["message"]

            await event_emitter.emit(
                run_id,
                "agent_response",
                PIPELINE_ARCHITECT,
                {
                    "text": (
                        f"{validation_error}\n\n"
                        "You can choose one of the predefined suggestions or enter a clearer custom rule."
                    )
                },
            )

    business_rules_yaml = build_business_rules_yaml(resolved_rules)
    business_rules_markdown = build_business_rules_markdown(resolved_rules)

    await artifact_store.write_artifact(
        run_id,
        PIPELINE_ARCHITECT,
        "business_rules.yml",
        business_rules_yaml,
        "yaml",
    )

    await artifact_store.write_artifact(
        run_id,
        PIPELINE_ARCHITECT,
        "business_rules.md",
        business_rules_markdown,
        "markdown",
    )

    return resolved_rules, business_rules_yaml, business_rules_markdown


async def run_multi_source_workflow(
    run_id: str,
    prompt: str,
    classification: dict[str, Any],
) -> None:
    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {
            "text": (
                "This request requires a multi-source data product.\n"
                f"Routing reason: {classification['reason']}\n"
                f"Matched terms: {', '.join(classification.get('matched_terms', [])) or 'n/a'}"
            )
        },
    )

    inspection = await multi_source_inspector(run_id, prompt)

    resolved_rules, business_rules_yaml, _ = await resolve_multi_source_business_questions(
        run_id=run_id,
        inspection=inspection,
    )

    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {
            "text": (
                f"All required reconciliation decisions are resolved. "
                f"I recorded {len(resolved_rules)} rule(s) in business_rules.yml. "
                "Now I will generate joined dbt models first, then tests, then final documentation artifacts."
            )
        },
    )

    source_profile_context = inspection["source_profile_context"]
    artifact_plan = inspection["artifact_plan"]
    registry.runs[run_id]["artifactPlan"] = artifact_plan

    await generate_artifacts_in_review_order(
        run_id=run_id,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_yaml,
        artifact_plan=artifact_plan,
    )

    final_mart = artifact_plan.get("final_mart_name", "configured final mart")
    package_name = artifact_plan.get("package_name", "Multi-Source Data Product Draft")
    model_files = artifact_plan.get("model_files", [])
    test_files = artifact_plan.get("test_files", [])
    documentation_files = artifact_plan.get("documentation_files", [])

    final_text = f"""Your {package_name} is ready for analytics review.

Selected data product:
{inspection["selection"]["data_product_name"]}

Sources:
{", ".join(inspection["selection"]["sources"])}

Relationships:
{", ".join(inspection["selection"]["relationships"])}

Final mart:
{final_mart}

Generated package:
- Multi-source profile
- Data quality report
- Relationship profile
- Join quality report
- Join plan
- Resolved business rules
- dbt model files: {", ".join(model_files) if model_files else "configured by artifact plan"}
- dbt test files: {", ".join(test_files) if test_files else "configured by artifact plan"}
- Documentation files: {", ".join(documentation_files) if documentation_files else "configured by artifact plan"}

Recommended next steps:
1. Review relationship_profile.md, join_quality_report.md, join_plan.md, and business_rules.yml.
2. Review the generated dbt SQL/YAML files.
3. Open the Pipeline tab and run the generated models into the demo data mart.
4. Preview the generated mart tables and download CSV/ZIP outputs if needed.
5. Validate reconciliation results with Finance before connecting to BI.
"""

    await event_emitter.emit(
        run_id,
        "final_message",
        PIPELINE_ARCHITECT,
        {"text": final_text},
    )
    await event_emitter.emit(
        run_id,
        "agent_completed",
        PIPELINE_ARCHITECT,
        {"status": "completed"},
    )

    registry.set_status(run_id, "completed")

    await event_emitter.emit(
        run_id,
        "done",
        PIPELINE_ARCHITECT,
        {"status": "completed"},
    )


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def run_pipeforge_workflow(run_id: str, prompt: str) -> None:
    try:
        registry.set_status(run_id, "running")

        await event_emitter.emit(
            run_id,
            "session_started",
            PIPELINE_ARCHITECT,
            {"prompt": prompt},
        )
        await event_emitter.emit(
            run_id,
            "agent_started",
            PIPELINE_ARCHITECT,
            {"status": "running"},
        )
        await event_emitter.emit(
            run_id,
            "agent_thinking",
            PIPELINE_ARCHITECT,
            {
                "text": (
                    "I will classify the request as direct analytics Q&A, single-source generation, or multi-source generation, "
                    "then either answer with safe SQL or generate a reviewable dbt package."
                )
            },
        )

        await asyncio.sleep(0.5)

        domain_classification = classify_domain_relevance(prompt)
        registry.runs[run_id]["domainRelevanceClassification"] = domain_classification

        if (
            domain_classification.get("needs_llm_fallback")
            and settings.use_llm_intent_classifier
        ):
            llm_classification = await classify_intent_with_llm(
                prompt=prompt,
                domain_classification=domain_classification,
            )
            registry.runs[run_id]["llmIntentClassification"] = llm_classification
            routing_classification = merge_domain_and_llm_classification(
                domain_classification=domain_classification,
                llm_classification=llm_classification,
            )
        else:
            routing_classification = _routing_from_domain_classification(domain_classification)

        registry.runs[run_id]["routingClassification"] = routing_classification

        if routing_classification["relevance"] == "out_of_scope":
            await _complete_run_with_message(
                run_id=run_id,
                agent_response=(
                    "I could not route this request to the PipeForge database or data product workflow.\n\n"
                    f"Reason: {routing_classification.get('reason', 'Out of scope.')}"
                ),
                message=(
                    "This request does not appear to be related to the available PipeForge "
                    "database or data product workflow.\n\n"
                    "I can help with customers, plans, subscriptions, invoices, payments, "
                    "billed revenue, collected revenue, MRR, outstanding invoice amount, "
                    "collection rate, or generated dbt-style artifacts."
                ),
            )
            return

        if (
            routing_classification["relevance"] == "ambiguous_database_request"
            or routing_classification.get("needs_clarification")
        ):
            await _complete_run_with_message(
                run_id=run_id,
                agent_response=(
                    "I need a little more detail before I can safely route this request.\n\n"
                    f"Reason: {routing_classification.get('reason', 'Ambiguous request.')}"
                ),
                message=_format_clarification_message(routing_classification),
            )
            return

        direct_classification = classify_direct_analytics_query(prompt)
        registry.runs[run_id]["directAnalyticsClassification"] = direct_classification

        if (
            direct_classification["is_direct_analytics_question"]
            or routing_classification.get("intent") == "direct_analytics_question"
        ):
            await event_emitter.emit(
                run_id,
                "agent_response",
                PIPELINE_ARCHITECT,
                {
                    "text": (
                        "This looks like a direct analytics question, so I will answer it by "
                        "using the semantic mapping layer, generating safe SQL, and executing it "
                        "on the demo database instead of generating a dbt package."
                    )
                },
            )

            result = await run_direct_analytics_query(run_id, prompt)

            await event_emitter.emit(
                run_id,
                "final_message",
                PIPELINE_ARCHITECT,
                {"text": result["chat_answer"]},
            )
            await event_emitter.emit(
                run_id,
                "agent_completed",
                PIPELINE_ARCHITECT,
                {"status": "completed"},
            )

            registry.set_status(run_id, "completed")

            await event_emitter.emit(
                run_id,
                "done",
                PIPELINE_ARCHITECT,
                {"status": "completed"},
            )
            return

        classification = classify_request_scope(prompt)
        registry.runs[run_id]["requestClassification"] = classification

        if classification["scope"] == "multi_source":
            await run_multi_source_workflow(
                run_id=run_id,
                prompt=prompt,
                classification=classification,
            )
            return

        selection = select_source_for_prompt(prompt)
        registry.runs[run_id]["selectedSource"] = selection

        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {
                "text": (
                    f"Selected source: `{selection['source_name']}`.\n"
                    f"Reason: {selection['reason']}\n"
                    f"Available sources: {', '.join(selection['available_sources'])}"
                )
            },
        )

        profile = await source_inspector(run_id, selection["source_name"])

        resolved_rules, business_rules_yaml, _ = await resolve_business_questions(
            run_id=run_id,
            profile=profile,
            user_request=prompt,
        )

        source_profile_context = profile["source_profile_context"]
        business_rules_context = business_rules_yaml
        artifact_plan = profile.get("artifact_plan", {})
        registry.runs[run_id]["artifactPlan"] = artifact_plan

        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {
                "text": (
                    f"All required business questions are resolved. "
                    f"I recorded {len(resolved_rules)} rule(s) in business_rules.yml. "
                    "Now I will generate model artifacts first, then test artifacts, then final documentation."
                )
            },
        )

        await generate_artifacts_in_review_order(
            run_id=run_id,
            source_profile_context=source_profile_context,
            business_rules_context=business_rules_context,
            artifact_plan=artifact_plan,
        )

        final_mart = artifact_plan.get("final_mart_name", "configured final mart")
        package_name = artifact_plan.get("package_name", "Data Product Draft")
        model_files = artifact_plan.get("model_files", [])
        test_files = artifact_plan.get("test_files", [])
        documentation_files = artifact_plan.get("documentation_files", [])

        final_text = f"""Your {package_name} is ready for analytics review.

Selected source:
{profile["source"]}

Final mart:
{final_mart}

Generated package:
- Source profile
- Data quality report
- Resolved business rules
- dbt model files: {", ".join(model_files) if model_files else "configured by artifact plan"}
- dbt test files: {", ".join(test_files) if test_files else "configured by artifact plan"}
- Documentation files: {", ".join(documentation_files) if documentation_files else "configured by artifact plan"}

Recommended next steps:
1. Review source_profile.md, data_quality_report.md, and business_rules.yml.
2. Review the generated dbt SQL/YAML files.
3. Open the Pipeline tab and run the generated models into the demo data mart.
4. Preview the generated mart tables and download CSV/ZIP outputs if needed.
5. Connect the final mart to your BI dashboard.
"""

        await event_emitter.emit(
            run_id,
            "final_message",
            PIPELINE_ARCHITECT,
            {"text": final_text},
        )
        await event_emitter.emit(
            run_id,
            "agent_completed",
            PIPELINE_ARCHITECT,
            {"status": "completed"},
        )

        registry.set_status(run_id, "completed")

        await event_emitter.emit(
            run_id,
            "done",
            PIPELINE_ARCHITECT,
            {"status": "completed"},
        )

    except Exception as exc:
        registry.set_status(run_id, "failed")

        await event_emitter.emit(
            run_id,
            "error",
            PIPELINE_ARCHITECT,
            {"message": str(exc)},
        )

        await event_emitter.emit(
            run_id,
            "agent_failed",
            PIPELINE_ARCHITECT,
            {
                "status": "failed",
                "message": str(exc),
            },
        )

        await event_emitter.emit(
            run_id,
            "done",
            PIPELINE_ARCHITECT,
            {"status": "failed"},
        )
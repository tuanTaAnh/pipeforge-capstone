import asyncio

from app.services.openhands_artifact_generator import (
    generate_doc_artifacts_with_openhands,
    generate_model_artifacts_with_openhands,
    generate_test_artifacts_with_openhands,
)

from app.schemas.agents import AgentInfo
from app.services.answer_queue import answer_queue
from app.services.artifact_store import artifact_store
from app.services.event_emitter import event_emitter
from app.services.run_registry import registry


PIPELINE_ARCHITECT = AgentInfo(
    id="pipeline-architect",
    name="Pipeline Architect",
    role="orchestrator",
    parentId=None,
)


def sub_agent(agent_id: str, name: str) -> AgentInfo:
    return AgentInfo(
        id=agent_id,
        name=name,
        role="sub_agent",
        parentId="pipeline-architect",
    )


async def source_inspector(run_id: str) -> None:
    agent = sub_agent("source-inspector", "Source Inspector")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {"text": "I need to profile the Stripe payments source before generating models."},
    )

    await event_emitter.emit(
        run_id,
        "tool_started",
        agent,
        {
            "toolCallId": "tool_profile_data",
            "toolName": "profile_data",
            "input": {"source": "stripe.payments"},
        },
    )

    await asyncio.sleep(1)

    profile_result = {
        "columns": [
            "payment_id",
            "customer_id",
            "amount",
            "currency",
            "status",
            "paid_at",
            "plan_id",
            "customer_segment",
            "discount_amount",
            "refunded_at",
        ],
        "rowCount": 125000,
        "qualityFindings": [
            "discount_amount is null in 45% of rows",
            "status contains paid, failed, refunded",
            "payment_id appears unique",
            "currency contains USD, EUR, GBP",
        ],
    }

    await event_emitter.emit(
        run_id,
        "tool_completed",
        agent,
        {
            "toolCallId": "tool_profile_data",
            "toolName": "profile_data",
            "output": profile_result,
        },
    )

    await artifact_store.write_artifact(
        run_id,
        agent,
        "source_profile.md",
        """# Source Profile: Stripe Payments

## Overview
Raw Stripe payments source used for revenue analytics.

## Data Quality Findings
- discount_amount is null in 45% of rows.
- status contains paid, failed, refunded.
- payment_id appears unique.
- currency contains USD, EUR, GBP.

## Required Decision
Missing discount values require a business rule before the revenue mart can be generated.
""",
        "markdown",
    )

    await event_emitter.emit(
        run_id,
        "sub_agent_completed",
        agent,
        {"status": "completed", "summary": "Source inspection completed."},
    )


async def model_builder(run_id: str, discount_rule: str) -> None:
    agent = sub_agent("model-builder", "Model Builder")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": "I will use OpenHands SDK to generate staging, intermediate, and mart dbt SQL models in a workspace."
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
                "targetFiles": [
                    "stg_stripe__payments.sql",
                    "int_payments__revenue_rules.sql",
                    "mart_revenue__monthly_by_segment.sql",
                ],
                "discountRule": discount_rule,
            },
        },
    )

    artifacts = await generate_model_artifacts_with_openhands(run_id, discount_rule)

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


async def test_writer(run_id: str, discount_rule: str) -> None:
    agent = sub_agent("test-writer", "Test Writer")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": "I will use OpenHands SDK to generate dbt schema tests and custom data quality checks."
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
                "targetFiles": [
                    "schema.yml",
                    "custom_tests/test_mrr_not_null.sql",
                ],
                "discountRule": discount_rule,
            },
        },
    )

    artifacts = await generate_test_artifacts_with_openhands(run_id, discount_rule)

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


async def doc_writer(run_id: str, discount_rule: str) -> None:
    agent = sub_agent("doc-writer", "Documentation Writer")

    await event_emitter.emit(run_id, "sub_agent_started", agent, {"status": "running"})
    await event_emitter.emit(
        run_id,
        "agent_thinking",
        agent,
        {
            "text": "I will use OpenHands SDK to document metrics, assumptions, and next steps."
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
                "targetFiles": ["pipeline_summary.md"],
                "discountRule": discount_rule,
            },
        },
    )

    artifacts = await generate_doc_artifacts_with_openhands(run_id, discount_rule)

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
            "summary": "Generated documentation using OpenHands SDK.",
        },
    )


async def run_mock_pipeforge_workflow(run_id: str, prompt: str) -> None:
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
                "text": "I will turn the business analytics request into a reviewable dbt pipeline package."
            },
        )

        await asyncio.sleep(0.8)

        await source_inspector(run_id)

        answer = await answer_queue.ask_user(
            run_id,
            PIPELINE_ARCHITECT,
            "The discount_amount column is null in 45% of rows. How should missing discounts be handled?",
            [
                "Treat missing discount as 0",
                "Exclude rows with missing discount",
                "Create a separate model for discounted vs full-price payments",
            ],
        )

        await event_emitter.emit(
            run_id,
            "agent_response",
            PIPELINE_ARCHITECT,
            {
                "text": f"Thanks. I will use this business rule: {answer}. Now I can fan out model, test, and documentation generation in parallel."
            },
        )

        await asyncio.gather(
            model_builder(run_id, answer),
            test_writer(run_id, answer),
            doc_writer(run_id, answer),
        )

        final_text = """Your Stripe Revenue Data Product Draft is ready for analytics review.

        Final mart:
        mart_revenue__monthly_by_segment
        
        Generated package:
        - Source profile
        - dbt staging model
        - dbt intermediate revenue-rules model
        - dbt monthly revenue mart
        - dbt schema tests
        - Custom MRR test
        - Pipeline summary documentation
        
        Recommended next steps:
        1. Review the business rules.
        2. Copy the files into your dbt project.
        3. Run dbt build and dbt test.
        4. Connect the final mart to your BI dashboard.
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
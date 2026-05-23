import asyncio
import shutil
from pathlib import Path
from typing import Dict, List, Literal, TypedDict

from pydantic import SecretStr

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool

from app.core.config import settings


ArtifactKind = Literal["sql", "yaml", "markdown", "json", "text"]


class GeneratedArtifact(TypedDict):
    filename: str
    type: ArtifactKind
    content: str


SOURCE_PROFILE_CONTEXT = """
Source: stripe.payments

Columns:
- payment_id
- customer_id
- amount
- currency
- status
- paid_at
- plan_id
- customer_segment
- discount_amount
- refunded_at

Data quality findings:
- discount_amount is null in 45% of rows.
- status contains paid, failed, refunded.
- payment_id appears unique.
- currency contains USD, EUR, GBP.
"""


def _artifact_type(filename: str) -> ArtifactKind:
    if filename.endswith(".sql"):
        return "sql"
    if filename.endswith(".yml") or filename.endswith(".yaml"):
        return "yaml"
    if filename.endswith(".md"):
        return "markdown"
    if filename.endswith(".json"):
        return "json"
    return "text"


def _build_agent() -> Agent:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY is missing")

    if not settings.llm_model:
        raise RuntimeError("LLM_MODEL is missing")

    llm = LLM(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=SecretStr(settings.llm_api_key),
    )

    return Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name=TaskTrackerTool.name),
        ],
    )


def _prepare_workspace(run_id: str, agent_slug: str) -> Path:
    workspace = settings.workspace_path / run_id / "openhands" / agent_slug

    if workspace.exists():
        shutil.rmtree(workspace)

    workspace.mkdir(parents=True, exist_ok=True)

    return workspace


def _read_expected_files(workspace: Path, expected_files: List[str]) -> List[GeneratedArtifact]:
    artifacts: List[GeneratedArtifact] = []

    missing: List[str] = []

    for filename in expected_files:
        path = workspace / filename

        if not path.exists():
            missing.append(filename)
            continue

        content = path.read_text(encoding="utf-8")

        if not content.strip():
            raise RuntimeError(f"OpenHands created empty file: {filename}")

        artifacts.append(
            {
                "filename": filename,
                "type": _artifact_type(filename),
                "content": content,
            }
        )

    if missing:
        files = sorted(str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file())
        raise RuntimeError(
            "OpenHands did not create required files. "
            f"Missing={missing}. Files found={files}"
        )

    return artifacts


def _run_openhands_task_sync(
    workspace: Path,
    task_prompt: str,
) -> None:
    agent = _build_agent()
    conversation = Conversation(agent=agent, workspace=str(workspace))
    conversation.send_message(task_prompt)
    conversation.run()


async def _run_openhands_task(
    workspace: Path,
    task_prompt: str,
) -> None:
    await asyncio.to_thread(_run_openhands_task_sync, workspace, task_prompt)


async def generate_model_artifacts_with_openhands(
    run_id: str,
    discount_rule: str,
) -> List[GeneratedArtifact]:
    expected_files = [
        "stg_stripe__payments.sql",
        "int_payments__revenue_rules.sql",
        "mart_revenue__monthly_by_segment.sql",
    ]

    workspace = _prepare_workspace(run_id, "model-builder")

    task_prompt = f"""
You are the Model Builder agent for PipeForge.

Your task:
Create exactly these 3 dbt SQL files in the current workspace root:
1. stg_stripe__payments.sql
2. int_payments__revenue_rules.sql
3. mart_revenue__monthly_by_segment.sql

Business goal:
Create a trusted monthly revenue dataset from Stripe payments for a Finance board dashboard.
The final mart should calculate monthly recurring revenue by customer segment.

Source profile:
{SOURCE_PROFILE_CONTEXT}

Confirmed business rule:
Missing discount handling = {discount_rule}

Requirements:
- Use dbt-style SQL with source() and ref().
- stg_stripe__payments.sql must normalize the raw source.
- If the business rule says missing discount should be treated as 0, use coalesce(discount_amount, 0).
- int_payments__revenue_rules.sql must define net_revenue_amount and is_revenue_eligible.
- Failed payments should not count as revenue.
- Refunded payments should reduce revenue.
- mart_revenue__monthly_by_segment.sql must aggregate:
  revenue_month,
  customer_segment,
  currency,
  monthly_recurring_revenue,
  active_paying_customers.

Important:
- Create only the requested files.
- Do not create explanations outside the files.
- Do not ask follow-up questions.
"""

    await _run_openhands_task(workspace, task_prompt)

    return _read_expected_files(workspace, expected_files)


async def generate_test_artifacts_with_openhands(
    run_id: str,
    discount_rule: str,
) -> List[GeneratedArtifact]:
    expected_files = [
        "schema.yml",
        "custom_tests/test_mrr_not_null.sql",
    ]

    workspace = _prepare_workspace(run_id, "test-writer")

    task_prompt = f"""
You are the Test Writer agent for PipeForge.

Your task:
Create exactly these files in the current workspace:
1. schema.yml
2. custom_tests/test_mrr_not_null.sql

Business goal:
Create dbt tests for a Stripe MRR data product.

Source profile:
{SOURCE_PROFILE_CONTEXT}

Confirmed business rule:
Missing discount handling = {discount_rule}

Requirements:
- schema.yml should include model descriptions and column tests.
- Include tests for payment_id uniqueness, not_null checks, accepted_values for status, and final mart metric quality.
- custom_tests/test_mrr_not_null.sql should check that monthly_recurring_revenue is not null in the final mart.
- Use dbt-compatible YAML/SQL.

Important:
- Create only the requested files.
- Do not ask follow-up questions.
"""

    await _run_openhands_task(workspace, task_prompt)

    return _read_expected_files(workspace, expected_files)


async def generate_doc_artifacts_with_openhands(
    run_id: str,
    discount_rule: str,
) -> List[GeneratedArtifact]:
    expected_files = [
        "pipeline_summary.md",
    ]

    workspace = _prepare_workspace(run_id, "doc-writer")

    task_prompt = f"""
    You are the Documentation Writer agent for PipeForge.
    
    Your task:
    Create exactly this file in the current workspace root:
    1. pipeline_summary.md
    
    Business goal:
    Document a Stripe Revenue Data Product Draft for analytics review.
    
    Source profile:
    {SOURCE_PROFILE_CONTEXT}
    
    Confirmed business rule:
    Missing discount handling = {discount_rule}
    
    Requirements:
    - Explain the purpose of the data product.
    - Name the final mart: mart_revenue__monthly_by_segment.
    - Explain metrics, dimensions, assumptions, and next steps.
    - Mention that analytics engineers should review the files, copy them into dbt, run dbt build/dbt test, then connect the final mart to BI.
    
    Important:
    - Create only pipeline_summary.md.
    - Do not ask follow-up questions.
    """

    await _run_openhands_task(workspace, task_prompt)

    return _read_expected_files(workspace, expected_files)
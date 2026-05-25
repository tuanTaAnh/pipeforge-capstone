import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import SecretStr

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool

from app.core.config import settings
from app.core.paths import PROMPTS_DIR


ArtifactKind = Literal["sql", "yaml", "markdown", "json", "text"]


class GeneratedArtifact(TypedDict):
    filename: str
    type: ArtifactKind
    content: str


OPENHANDS_TIMEOUT_SECONDS = int(os.getenv("OPENHANDS_TIMEOUT_SECONDS", "180"))
OPENHANDS_MAX_CONCURRENCY = int(os.getenv("OPENHANDS_MAX_CONCURRENCY", "1"))
OPENHANDS_TASK_DELAY_SECONDS = float(os.getenv("OPENHANDS_TASK_DELAY_SECONDS", "0"))
OPENHANDS_REPAIR_ATTEMPTS = int(os.getenv("OPENHANDS_REPAIR_ATTEMPTS", "1"))

_OPENHANDS_SEMAPHORE = asyncio.Semaphore(max(1, OPENHANDS_MAX_CONCURRENCY))


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

    llm_kwargs = {
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "api_key": SecretStr(settings.llm_api_key),
    }

    if "deepseek-v4-flash-free" in settings.llm_model:
        llm_kwargs["thinking"] = {"type": "disabled"}

    llm = LLM(**llm_kwargs)

    return Agent(
        llm=llm,
        tools=[
            Tool(name=FileEditorTool.name),
        ],
    )


def _format_relative_files(files: list[str]) -> str:
    return "\n".join(f"- {filename}" for filename in files)


def _format_absolute_files(workspace: Path, files: list[str]) -> str:
    return "\n".join(f"- {workspace / filename}" for filename in files)


def _format_artifact_plan_context(artifact_plan: dict[str, Any]) -> str:
    return json.dumps(artifact_plan, ensure_ascii=False, indent=2, default=str)


def _artifact_plan_files(
    artifact_plan: dict[str, Any],
    key: str,
    fallback: list[str],
) -> list[str]:
    value = artifact_plan.get(key)

    if not isinstance(value, list):
        return fallback

    files = [str(item).strip() for item in value if str(item).strip()]

    return files or fallback


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename

    if not path.exists():
        raise RuntimeError(f"Prompt file not found: {path}")

    return path.read_text(encoding="utf-8")


def _render_prompt(
    template: str,
    workspace: Path,
    expected_files: list[str],
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
    missing_files: list[str] | None = None,
    original_task_prompt: str | None = None,
) -> str:
    missing_files = missing_files or []

    replacements = {
        "{{WORKSPACE_ROOT}}": str(workspace),
        "{{SOURCE_PROFILE_CONTEXT}}": source_profile_context,
        "{{BUSINESS_RULES_CONTEXT}}": business_rules_context,
        "{{ARTIFACT_PLAN_CONTEXT}}": _format_artifact_plan_context(artifact_plan),
        "{{EXPECTED_FILES}}": _format_relative_files(expected_files),
        "{{EXPECTED_ABSOLUTE_PATHS}}": _format_absolute_files(workspace, expected_files),
        "{{MISSING_FILES}}": _format_relative_files(missing_files),
        "{{MISSING_ABSOLUTE_PATHS}}": _format_absolute_files(workspace, missing_files),
        "{{ORIGINAL_TASK_PROMPT}}": original_task_prompt or "",
    }

    rendered = template

    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    return rendered.strip()


def _prepare_workspace(
    run_id: str,
    agent_slug: str,
    expected_files: list[str] | None = None,
) -> Path:
    workspace = settings.workspace_path / run_id / "openhands" / agent_slug

    if workspace.exists():
        shutil.rmtree(workspace)

    workspace.mkdir(parents=True, exist_ok=True)

    agents_md = workspace / "AGENTS.md"
    agents_md.write_text(
        "\n".join(
            [
                "# PipeForge Agent Workspace",
                "",
                "This workspace is intentionally minimal and task-scoped.",
                f"Current workspace root: {workspace}",
                "",
                "Execution rules:",
                "- Do not inspect the filesystem.",
                "- Do not search for an existing dbt project.",
                "- Do not inspect parent folders or sibling folders.",
                "- Do not use relative paths such as '.', '..', './', or '../'.",
                "- Do not use file_editor view unless the user explicitly asks for inspection.",
                "- Use file_editor create to create only the exact files requested in the task prompt.",
                "- Use absolute paths only.",
                "- Do not create README, notes, alternative files, or extra outputs.",
                "- Do not modify this AGENTS.md file.",
                "- Do not call finish until all requested files have been created.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    for filename in expected_files or []:
        parent_dir = (workspace / filename).parent
        parent_dir.mkdir(parents=True, exist_ok=True)

    return workspace


def _list_workspace_files(workspace: Path) -> list[str]:
    return sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*")
        if path.is_file()
    )


def _collect_expected_files(
    workspace: Path,
    expected_files: list[str],
) -> tuple[list[GeneratedArtifact], list[str], list[str]]:
    artifacts: list[GeneratedArtifact] = []
    missing: list[str] = []
    empty: list[str] = []

    for filename in expected_files:
        path = workspace / filename

        if not path.exists():
            missing.append(filename)
            continue

        content = path.read_text(encoding="utf-8")

        if not content.strip():
            empty.append(filename)
            continue

        artifacts.append(
            {
                "filename": filename,
                "type": _artifact_type(filename),
                "content": content,
            }
        )

    return artifacts, missing, empty


def _raise_missing_or_empty_files(
    workspace: Path,
    missing: list[str],
    empty: list[str],
) -> None:
    files_found = _list_workspace_files(workspace)

    problems: list[str] = []

    if missing:
        problems.append(f"Missing={missing}")

    if empty:
        problems.append(f"Empty={empty}")

    raise RuntimeError(
        "OpenHands did not create required files. "
        f"{'. '.join(problems)}. "
        f"Files found={files_found}"
    )


def _delete_empty_files(workspace: Path, empty_files: list[str]) -> None:
    for filename in empty_files:
        path = workspace / filename

        if path.exists() and path.is_file() and not path.read_text(encoding="utf-8").strip():
            path.unlink()


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
    timeout_seconds: int = OPENHANDS_TIMEOUT_SECONDS,
) -> None:
    async with _OPENHANDS_SEMAPHORE:
        if OPENHANDS_TASK_DELAY_SECONDS > 0:
            await asyncio.sleep(OPENHANDS_TASK_DELAY_SECONDS)

        try:
            await asyncio.wait_for(
                asyncio.to_thread(_run_openhands_task_sync, workspace, task_prompt),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"OpenHands task timed out after {timeout_seconds} seconds."
            ) from exc


async def _run_task_and_collect_with_repair(
    workspace: Path,
    task_prompt: str,
    expected_files: list[str],
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> list[GeneratedArtifact]:
    await _run_openhands_task(workspace, task_prompt)

    artifacts, missing, empty = _collect_expected_files(workspace, expected_files)

    if not missing and not empty:
        return artifacts

    for _ in range(OPENHANDS_REPAIR_ATTEMPTS):
        _delete_empty_files(workspace, empty)

        repair_template = _load_prompt("repair_prompt.txt")
        repair_prompt = _render_prompt(
            template=repair_template,
            workspace=workspace,
            expected_files=expected_files,
            source_profile_context=source_profile_context,
            business_rules_context=business_rules_context,
            artifact_plan=artifact_plan,
            missing_files=[*missing, *empty],
            original_task_prompt=task_prompt,
        )

        await _run_openhands_task(workspace, repair_prompt)

        artifacts, missing, empty = _collect_expected_files(workspace, expected_files)

        if not missing and not empty:
            return artifacts

    _raise_missing_or_empty_files(workspace, missing, empty)


async def generate_model_artifacts_with_openhands(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> list[GeneratedArtifact]:
    expected_files = _artifact_plan_files(
        artifact_plan,
        "model_files",
        [
            "stg_source__table.sql",
            "int_table__rules.sql",
            "mart_table__summary.sql",
        ],
    )

    workspace = _prepare_workspace(run_id, "model-builder", expected_files)

    prompt_template = _load_prompt("model_builder_prompt.txt")
    task_prompt = _render_prompt(
        template=prompt_template,
        workspace=workspace,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    return await _run_task_and_collect_with_repair(
        workspace=workspace,
        task_prompt=task_prompt,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )


async def generate_test_artifacts_with_openhands(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> list[GeneratedArtifact]:
    expected_files = _artifact_plan_files(
        artifact_plan,
        "test_files",
        [
            "schema.yml",
            "custom_tests/test_primary_metric_not_null.sql",
        ],
    )

    workspace = _prepare_workspace(run_id, "test-writer", expected_files)

    prompt_template = _load_prompt("test_writer_prompt.txt")
    task_prompt = _render_prompt(
        template=prompt_template,
        workspace=workspace,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    return await _run_task_and_collect_with_repair(
        workspace=workspace,
        task_prompt=task_prompt,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )


async def generate_doc_artifacts_with_openhands(
    run_id: str,
    source_profile_context: str,
    business_rules_context: str,
    artifact_plan: dict[str, Any],
) -> list[GeneratedArtifact]:
    expected_files = _artifact_plan_files(
        artifact_plan,
        "documentation_files",
        [
            "pipeline_summary.md",
        ],
    )

    workspace = _prepare_workspace(run_id, "doc-writer", expected_files)

    prompt_template = _load_prompt("documentation_writer_prompt.txt")
    task_prompt = _render_prompt(
        template=prompt_template,
        workspace=workspace,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )

    return await _run_task_and_collect_with_repair(
        workspace=workspace,
        task_prompt=task_prompt,
        expected_files=expected_files,
        source_profile_context=source_profile_context,
        business_rules_context=business_rules_context,
        artifact_plan=artifact_plan,
    )
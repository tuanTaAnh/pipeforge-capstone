from __future__ import annotations

import re
from typing import Any

from app.schemas.llm_plans import ArtifactPlan, RequestPlan


class ArtifactPlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_MAX_MODEL_FILES = 8
_MAX_TEST_FILES = 3
_MAX_DOCUMENTATION_FILES = 2
_MAX_ASSUMPTIONS = 3
_MAX_WARNINGS = 3
_MAX_TEXT_CHARS = 240
_MAX_LIST_ITEM_CHARS = 140


def validate_artifact_plan(plan: ArtifactPlan, request_plan: RequestPlan, metadata_context: dict[str, Any]) -> None:
    errors: list[str] = []

    allowed_sources = set(metadata_context.get("allowed_sources", []))
    selected_sources = plan.selected_sources or request_plan.selected_sources

    for source in selected_sources:
        if source not in allowed_sources:
            errors.append(f"Artifact plan selected unknown source: {source}")

    if not plan.model_files:
        errors.append("Artifact plan must include at least one SQL model file.")
    if not plan.test_files:
        errors.append("Artifact plan should include schema.yml or custom test files.")
    if not plan.documentation_files:
        errors.append("Artifact plan should include documentation files.")

    if len(plan.model_files) > _MAX_MODEL_FILES:
        errors.append(f"Artifact plan has too many model files: {len(plan.model_files)} > {_MAX_MODEL_FILES}")
    if len(plan.test_files) > _MAX_TEST_FILES:
        errors.append(f"Artifact plan has too many test files: {len(plan.test_files)} > {_MAX_TEST_FILES}")
    if len(plan.documentation_files) > _MAX_DOCUMENTATION_FILES:
        errors.append(f"Artifact plan has too many documentation files: {len(plan.documentation_files)} > {_MAX_DOCUMENTATION_FILES}")
    if len(plan.assumptions) > _MAX_ASSUMPTIONS:
        errors.append(f"Artifact plan has too many assumptions: {len(plan.assumptions)} > {_MAX_ASSUMPTIONS}")
    if len(plan.warnings) > _MAX_WARNINGS:
        errors.append(f"Artifact plan has too many warnings: {len(plan.warnings)} > {_MAX_WARNINGS}")

    if len(plan.business_interpretation) > _MAX_TEXT_CHARS:
        errors.append("Artifact plan business_interpretation is too long.")

    for field_name, values in [
        ("assumptions", plan.assumptions),
        ("warnings", plan.warnings),
    ]:
        for value in values:
            if len(value) > _MAX_LIST_ITEM_CHARS:
                errors.append(f"Artifact plan {field_name} item is too long: {value[:80]}...")

    all_files = [*plan.model_files, *plan.test_files, *plan.documentation_files]
    if len(all_files) != len(set(all_files)):
        errors.append("Artifact plan contains duplicate filenames.")

    for filename in all_files:
        if not _SAFE_FILE_RE.match(filename):
            errors.append(f"Unsafe artifact filename: {filename}")
        if filename.startswith("/") or ".." in filename.split("/"):
            errors.append(f"Artifact filename must be relative and stay inside workspace: {filename}")

    for filename in plan.model_files:
        if not filename.endswith(".sql"):
            errors.append(f"Model file must be .sql: {filename}")

    if errors:
        raise ArtifactPlanValidationError(errors)


def normalize_artifact_plan(plan: ArtifactPlan, request_plan: RequestPlan) -> ArtifactPlan:
    if not plan.selected_sources:
        plan.selected_sources = list(request_plan.selected_sources)
    if not plan.source_name:
        plan.source_name = request_plan.selected_data_product or (plan.selected_sources[0] if plan.selected_sources else "llm_selected_sources")
    if not plan.package_name:
        plan.package_name = "PipeForge Data Product Draft"
    if not plan.final_mart_name and plan.model_files:
        plan.final_mart_name = plan.model_files[-1].removesuffix(".sql")

    plan.model_files = _dedupe(plan.model_files)[:_MAX_MODEL_FILES]
    plan.test_files = _dedupe(plan.test_files)[:_MAX_TEST_FILES]
    plan.documentation_files = _dedupe(plan.documentation_files)[:_MAX_DOCUMENTATION_FILES]
    plan.assumptions = _dedupe_short(plan.assumptions, max_items=_MAX_ASSUMPTIONS, max_chars=_MAX_LIST_ITEM_CHARS)
    plan.warnings = _dedupe_short(plan.warnings, max_items=_MAX_WARNINGS, max_chars=_MAX_LIST_ITEM_CHARS)
    plan.business_interpretation = _short_text(plan.business_interpretation, max_chars=_MAX_TEXT_CHARS)

    # generation_notes used to make Step 8B verbose and fragile. Keep the schema
    # backward-compatible, but never propagate notes into artifact_plan.json.
    if hasattr(plan, "generation_notes"):
        plan.generation_notes = []

    return plan


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dedupe_short(values: list[str], *, max_items: int, max_chars: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _short_text(value, max_chars=max_chars)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


def _short_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
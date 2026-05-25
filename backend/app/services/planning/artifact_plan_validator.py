from __future__ import annotations

import re
from typing import Any

from app.schemas.llm_plans import ArtifactPlan, RequestPlan


class ArtifactPlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


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
    return plan

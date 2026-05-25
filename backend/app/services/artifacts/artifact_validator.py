from __future__ import annotations

import re
from typing import Any

import yaml

from app.services.pipeline.dbt_sql_compiler import extract_ref_dependencies, extract_source_dependencies
from app.services.pipeline.pipeline_sql_safety_validator import validate_pipeline_model_sql


class ArtifactValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_generated_artifacts(
    *,
    artifacts: list[dict[str, Any]],
    artifact_plan: dict[str, Any],
    allowed_sources: list[str],
) -> dict[str, Any]:
    errors: list[str] = []
    filenames = {artifact.get("filename") for artifact in artifacts}
    expected_files = set(artifact_plan.get("model_files", [])) | set(artifact_plan.get("test_files", [])) | set(artifact_plan.get("documentation_files", []))

    missing = sorted(filename for filename in expected_files if filename not in filenames)
    if missing:
        errors.append(f"Missing expected artifacts: {missing}")

    for artifact in artifacts:
        filename = str(artifact.get("filename", ""))
        content = str(artifact.get("content", ""))

        if not content.strip():
            errors.append(f"Artifact is empty: {filename}")
            continue

        if filename.endswith(('.yml', '.yaml')):
            try:
                yaml.safe_load(content)
            except Exception as exc:
                errors.append(f"Invalid YAML in {filename}: {exc}")

        if filename.endswith(".sql") and not filename.startswith("custom_tests/"):
            try:
                validate_pipeline_model_sql(content)
            except Exception as exc:
                errors.append(f"Unsafe/non-select model SQL in {filename}: {exc}")

            for source in extract_source_dependencies(content):
                # source may be rendered as source_name.table or similar depending compiler extraction.
                source_text = ".".join(source) if isinstance(source, tuple) else str(source)
                if not any(allowed_source in source_text for allowed_source in allowed_sources):
                    errors.append(f"{filename} references non-selected source `{source_text}`")

            _validate_no_obvious_unknown_source(filename, content, allowed_sources, errors)

    if errors:
        raise ArtifactValidationError(sorted(set(errors)))

    return {"valid": True, "checked_files": sorted(filenames), "errors": []}


def _validate_no_obvious_unknown_source(filename: str, content: str, allowed_sources: list[str], errors: list[str]) -> None:
    suspicious = {"fx_rates", "exchange_rates", "currency_rates", "calendar", "date_spine"}
    lowered = content.lower()
    for term in suspicious:
        if term in lowered and not any(term == source.lower() for source in allowed_sources):
            errors.append(f"{filename} appears to reference unavailable source/table `{term}`")

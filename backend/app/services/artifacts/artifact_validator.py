from __future__ import annotations

from typing import Any

import yaml

from app.services.pipeline.dbt_sql_compiler import extract_ref_dependencies, extract_source_dependencies
from app.services.pipeline.pipeline_sql_safety_validator import validate_pipeline_model_sql
from app.services.validation.validation_context import ValidationContext, build_validation_context_from_sources, format_source_ref


class ArtifactValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_generated_artifacts(
    *,
    artifacts: list[dict[str, Any]],
    artifact_plan: dict[str, Any],
    allowed_sources: list[str] | None = None,
    validation_context: ValidationContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate generated artifacts against one run-level validation context.

    The source whitelist must come from selected contracts / artifact plan, not
    from generated files. This prevents partial generation order from changing
    which raw sources are considered available.
    """
    context = _coerce_validation_context(
        validation_context=validation_context,
        allowed_sources=allowed_sources or artifact_plan.get("selected_sources", []),
        artifact_plan=artifact_plan,
    )

    errors: list[str] = []
    filenames = {str(artifact.get("filename")) for artifact in artifacts if artifact.get("filename")}
    expected_files = (
        set(artifact_plan.get("model_files", []))
        | set(artifact_plan.get("test_files", []))
        | set(artifact_plan.get("documentation_files", []))
    )
    expected_model_names = {filename.removesuffix(".sql").split("/")[-1] for filename in artifact_plan.get("model_files", [])}

    missing = sorted(filename for filename in expected_files if filename not in filenames)
    if missing:
        errors.append(f"Missing expected artifacts: {missing}")

    for artifact in artifacts:
        filename = str(artifact.get("filename", ""))
        content = str(artifact.get("content", ""))

        if not content.strip():
            errors.append(f"Artifact is empty: {filename}")
            continue

        if filename.endswith((".yml", ".yaml")):
            try:
                yaml.safe_load(content)
            except Exception as exc:
                errors.append(f"Invalid YAML in {filename}: {exc}")

        if filename.endswith(".sql") and not filename.startswith("custom_tests/"):
            try:
                validate_pipeline_model_sql(content)
            except Exception as exc:
                errors.append(f"Unsafe/non-select model SQL in {filename}: {exc}")

            _validate_source_refs(filename, content, context, errors)
            _validate_ref_dependencies(filename, content, expected_model_names, errors)
            _validate_no_obvious_unknown_source(filename, content, context, errors)

    if errors:
        raise ArtifactValidationError(sorted(set(errors)))

    return {
        "valid": True,
        "checked_files": sorted(filenames),
        "errors": [],
        "allowed_source_refs": context.allowed_source_refs,
    }


def _coerce_validation_context(
    *,
    validation_context: ValidationContext | dict[str, Any] | None,
    allowed_sources: list[str],
    artifact_plan: dict[str, Any],
) -> ValidationContext:
    if isinstance(validation_context, ValidationContext):
        return validation_context
    if isinstance(validation_context, dict) and validation_context.get("allowed_source_dependencies"):
        from app.services.validation.validation_context import validation_context_from_dict

        parsed = validation_context_from_dict(validation_context)
        if parsed:
            return parsed
    return build_validation_context_from_sources(selected_sources=allowed_sources, artifact_plan=artifact_plan)


def _validate_source_refs(filename: str, content: str, context: ValidationContext, errors: list[str]) -> None:
    for dependency in extract_source_dependencies(content):
        if dependency not in context.allowed_source_dependencies:
            allowed_text = ", ".join(context.allowed_source_refs) or "none"
            errors.append(
                f"{filename} references non-selected source `{format_source_ref(dependency)}`. "
                f"Allowed source refs for this run: {allowed_text}"
            )


def _validate_ref_dependencies(filename: str, content: str, expected_model_names: set[str], errors: list[str]) -> None:
    for model_name in extract_ref_dependencies(content):
        if model_name not in expected_model_names:
            errors.append(
                f"{filename} references non-generated model `{model_name}`. "
                f"Expected generated models: {sorted(expected_model_names)}"
            )


def _validate_no_obvious_unknown_source(filename: str, content: str, context: ValidationContext, errors: list[str]) -> None:
    suspicious = {"fx_rates", "exchange_rates", "currency_rates", "calendar", "date_spine"}
    allowed_source_names = {item.lower() for item in context.selected_source_names}
    allowed_source_names.update({dependency[1].lower() for dependency in context.allowed_source_dependencies})
    lowered = content.lower()
    for term in suspicious:
        if term in lowered and term not in allowed_source_names:
            errors.append(f"{filename} appears to reference unavailable source/table `{term}`")

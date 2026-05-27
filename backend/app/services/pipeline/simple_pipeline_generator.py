from __future__ import annotations

import json
from typing import Any


class SimplePipelineConfigError(ValueError):
    pass


def find_simple_pipeline_generation_config(
    *,
    metadata_context: dict[str, Any],
    request_plan: Any,
    previous_user_answers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a YAML-driven simple-pipeline generation config.

    This keeps Python generic: database-specific source/metric/model names live in
    clarification_rules.yml option metadata. The function supports two paths:
    - user answered a clarification option that declares generation.mode=simple_pipeline
    - planner selected the same simple source/metric explicitly without a user answer
    """
    answered = _find_config_from_previous_answers(
        metadata_context=metadata_context,
        previous_user_answers=previous_user_answers,
    )
    if answered:
        return answered

    return _find_config_from_request_plan(
        metadata_context=metadata_context,
        request_plan=request_plan,
    )


def build_simple_pipeline_package(
    *,
    metadata_context: dict[str, Any],
    request_plan: Any,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build deterministic runnable SQL/YAML/docs artifacts for a simple pipeline."""
    generation = _generation_config(config)
    option = config.get("option", {}) if isinstance(config.get("option"), dict) else {}

    source_name = _required_text(generation, "source")
    source = _get_source(metadata_context, source_name)
    source_ref = str(source.get("dbt_source") or "").strip()
    if not source_ref:
        raise SimplePipelineConfigError(f"Source `{source_name}` does not define dbt_source in metadata.")

    staging_model = _required_text(generation, "staging_model")
    mart_model = _required_text(generation, "mart_model")
    time_dimension = _required_text(generation, "time_dimension")
    value_column = _required_text(generation, "value_column")
    output_metric = _required_text(generation, "output_metric")

    columns = source.get("columns", {}) if isinstance(source.get("columns"), dict) else {}
    _require_source_column(columns, time_dimension, source_name)
    _require_source_column(columns, value_column, source_name)

    staging_columns = _string_list(generation.get("staging_columns")) or list(columns.keys())
    staging_columns = [column for column in staging_columns if column in columns]
    if time_dimension not in staging_columns:
        staging_columns.append(time_dimension)
    if value_column not in staging_columns:
        staging_columns.append(value_column)

    package_name = str(generation.get("package_name") or option.get("label") or "Simple Pipeline Draft")
    final_mart_name = str(generation.get("final_mart_name") or mart_model)
    model_files = _string_list(generation.get("model_files")) or [f"{staging_model}.sql", f"{mart_model}.sql"]
    test_files = _string_list(generation.get("test_files")) or ["schema.yml"]
    documentation_files = _string_list(generation.get("documentation_files")) or ["pipeline_summary.md"]

    selected_sources = _string_list(generation.get("selected_sources")) or _string_list(option.get("selected_sources")) or [source_name]
    selected_metrics = _string_list(generation.get("selected_metrics")) or _string_list(option.get("selected_metrics")) or _string_list(getattr(request_plan, "selected_metrics", []))
    selected_dimensions = _string_list(generation.get("selected_dimensions")) or _string_list(option.get("selected_dimensions")) or _string_list(getattr(request_plan, "selected_dimensions", []))

    artifact_plan = {
        "package_name": package_name,
        "source_name": str(generation.get("source_name") or source_name),
        "selected_sources": selected_sources,
        "final_mart_name": final_mart_name,
        "model_files": model_files,
        "test_files": test_files,
        "documentation_files": documentation_files,
        "business_interpretation": str(
            generation.get("business_interpretation")
            or option.get("resolved_rule")
            or getattr(request_plan, "business_interpretation", "")
            or f"Build a simple pipeline for {output_metric}."
        ),
        "assumptions": _dedupe(
            [
                *_string_list(getattr(request_plan, "assumptions", [])),
                str(option.get("resolved_rule") or "").strip(),
            ]
        ),
        "warnings": _string_list(getattr(request_plan, "warnings", [])),
        "generation_mode": "simple_pipeline",
        "selected_metrics": selected_metrics,
        "selected_dimensions": selected_dimensions,
    }

    staging_sql = _render_staging_sql(
        source_name=source_name,
        source_ref=source_ref,
        staging_columns=staging_columns,
    )
    mart_sql = _render_monthly_metric_mart_sql(
        staging_model=staging_model,
        time_dimension=time_dimension,
        value_column=value_column,
        output_metric=output_metric,
        final_mart_name=final_mart_name,
        coalesce_value=bool(generation.get("coalesce_value", True)),
    )
    schema_yml = _render_schema_yml(
        staging_model=staging_model,
        mart_model=mart_model,
        time_dimension=time_dimension,
        output_metric=output_metric,
        source_name=source_name,
        package_name=package_name,
    )
    summary_md = _render_pipeline_summary(
        package_name=package_name,
        source_name=source_name,
        source_ref=source_ref,
        staging_model=staging_model,
        mart_model=mart_model,
        time_dimension=time_dimension,
        value_column=value_column,
        output_metric=output_metric,
        option=option,
    )

    artifacts_by_name = {
        f"{staging_model}.sql": staging_sql,
        f"{mart_model}.sql": mart_sql,
        "schema.yml": schema_yml,
        "pipeline_summary.md": summary_md,
    }

    artifacts: list[dict[str, Any]] = []
    for filename in [*model_files, *test_files, *documentation_files]:
        content = artifacts_by_name.get(filename)
        if content is None:
            raise SimplePipelineConfigError(
                f"Simple pipeline generator does not know how to render expected file `{filename}`. "
                "Keep simple_pipeline model_files/test_files/documentation_files aligned with the configured template."
            )
        artifacts.append(
            {
                "filename": filename,
                "content": content,
                "type": _artifact_type(filename),
            }
        )

    return artifact_plan, artifacts


def _find_config_from_previous_answers(
    *,
    metadata_context: dict[str, Any],
    previous_user_answers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for answer in reversed(previous_user_answers):
        if not isinstance(answer, dict):
            continue
        question_id = str(answer.get("questionId") or answer.get("question_id") or "").strip()
        option_id = str(answer.get("selectedOptionId") or answer.get("selected_option_id") or "").strip()
        if not question_id or not option_id:
            continue

        for rule in _clarification_rules(metadata_context):
            clarification = rule.get("clarification") if isinstance(rule.get("clarification"), dict) else {}
            rule_question_id = str(clarification.get("id") or rule.get("id") or "").strip()
            if rule_question_id != question_id:
                continue
            for option in _rule_options(rule):
                if str(option.get("id") or "").strip() == option_id and _is_simple_pipeline_option(option):
                    return {"rule": rule, "option": option, "answer": answer, "generation": option.get("generation")}
    return None


def _find_config_from_request_plan(*, metadata_context: dict[str, Any], request_plan: Any) -> dict[str, Any] | None:
    plan_sources = set(_string_list(getattr(request_plan, "selected_sources", [])))
    plan_metrics = set(_string_list(getattr(request_plan, "selected_metrics", [])))
    plan_dimensions = set(_string_list(getattr(request_plan, "selected_dimensions", [])))

    if not plan_sources or not plan_metrics:
        return None

    for rule in _clarification_rules(metadata_context):
        for option in _rule_options(rule):
            if not _is_simple_pipeline_option(option):
                continue
            option_sources = set(_string_list(option.get("selected_sources")))
            option_metrics = set(_string_list(option.get("selected_metrics")))
            option_dimensions = set(_string_list(option.get("selected_dimensions")))
            if option_sources and option_sources.issubset(plan_sources) and option_metrics and option_metrics.issubset(plan_metrics):
                if not option_dimensions or option_dimensions.issubset(plan_dimensions):
                    return {"rule": rule, "option": option, "answer": None, "generation": option.get("generation")}
    return None


def _is_simple_pipeline_option(option: dict[str, Any]) -> bool:
    generation = option.get("generation") if isinstance(option.get("generation"), dict) else {}
    mode = str(generation.get("mode") or generation.get("strategy") or "").strip().lower()
    return mode == "simple_pipeline"


def _generation_config(config: dict[str, Any]) -> dict[str, Any]:
    generation = config.get("generation") if isinstance(config.get("generation"), dict) else {}
    if not generation:
        option = config.get("option") if isinstance(config.get("option"), dict) else {}
        generation = option.get("generation") if isinstance(option.get("generation"), dict) else {}
    if not generation:
        raise SimplePipelineConfigError("Missing simple pipeline generation config.")
    return generation


def _clarification_rules(metadata_context: dict[str, Any]) -> list[dict[str, Any]]:
    rules = metadata_context.get("clarification_rules", [])
    return [rule for rule in rules if isinstance(rule, dict) and rule.get("enabled", True)] if isinstance(rules, list) else []


def _rule_options(rule: dict[str, Any]) -> list[dict[str, Any]]:
    options = rule.get("options", [])
    return [option for option in options if isinstance(option, dict)] if isinstance(options, list) else []


def _get_source(metadata_context: dict[str, Any], source_name: str) -> dict[str, Any]:
    source = metadata_context.get("sources", {}).get(source_name)
    if not isinstance(source, dict):
        raise SimplePipelineConfigError(f"Unknown source in simple pipeline config: `{source_name}`")
    return source


def _required_text(value: dict[str, Any], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise SimplePipelineConfigError(f"Missing required simple pipeline config field: `{key}`")
    return text


def _require_source_column(columns: dict[str, Any], column_name: str, source_name: str) -> None:
    if column_name not in columns:
        raise SimplePipelineConfigError(f"Column `{column_name}` is not defined on selected source `{source_name}`.")


def _render_staging_sql(*, source_name: str, source_ref: str, staging_columns: list[str]) -> str:
    column_lines = ",\n        ".join(staging_columns)
    return f"""-- Staging model for {source_name}
SELECT
        {column_lines}
FROM {{{{ {source_ref} }}}}
"""


def _render_monthly_metric_mart_sql(
    *,
    staging_model: str,
    time_dimension: str,
    value_column: str,
    output_metric: str,
    final_mart_name: str,
    coalesce_value: bool,
) -> str:
    value_expression = f"COALESCE({value_column}, 0)" if coalesce_value else value_column
    return f"""-- Mart model: {final_mart_name}
SELECT
    {time_dimension},
    SUM({value_expression}) AS {output_metric}
FROM {{{{ ref('{staging_model}') }}}}
GROUP BY {time_dimension}
ORDER BY {time_dimension}
"""


def _render_schema_yml(
    *,
    staging_model: str,
    mart_model: str,
    time_dimension: str,
    output_metric: str,
    source_name: str,
    package_name: str,
) -> str:
    return f"""version: 2

models:
  - name: {staging_model}
    description: Staging model for {source_name} used by {package_name}.
    columns:
      - name: {time_dimension}
        tests:
          - not_null

  - name: {mart_model}
    description: Monthly metric mart generated by PipeForge simple pipeline mode.
    columns:
      - name: {time_dimension}
        tests:
          - not_null
      - name: {output_metric}
        tests:
          - not_null
"""


def _render_pipeline_summary(
    *,
    package_name: str,
    source_name: str,
    source_ref: str,
    staging_model: str,
    mart_model: str,
    time_dimension: str,
    value_column: str,
    output_metric: str,
    option: dict[str, Any],
) -> str:
    resolved_rule = str(option.get("resolved_rule") or "").strip()
    implementation = str(option.get("implementation") or "").strip()
    return f"""# {package_name}

## Overview

This package was generated with PipeForge simple pipeline mode for a straightforward monthly metric pipeline.

## Selected source

- Source: `{source_name}`
- Raw source ref: `{{{{ {source_ref} }}}}`

## Generated models

- `{staging_model}`: selects the configured source columns from the raw source.
- `{mart_model}`: groups by `{time_dimension}` and calculates `{output_metric}`.

## Metric logic

```sql
SELECT
  {time_dimension},
  SUM(COALESCE({value_column}, 0)) AS {output_metric}
FROM {{{{ ref('{staging_model}') }}}}
GROUP BY {time_dimension}
```

## Business rule

{resolved_rule or 'No additional business rule was provided.'}

## Implementation note

{implementation or 'The metric is generated from the selected metadata configuration.'}
"""


def _artifact_type(filename: str) -> str:
    if filename.endswith(".sql"):
        return "sql"
    if filename.endswith((".yml", ".yaml")):
        return "yaml"
    if filename.endswith(".json"):
        return "json"
    return "markdown"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


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


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

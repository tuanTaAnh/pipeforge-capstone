from __future__ import annotations

import csv
import io
import json
import re
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services.database.database_service import get_database_path, quote_identifier
from app.services.pipeline.dbt_sql_compiler import (
    compile_dbt_sql_to_sqlite,
    extract_ref_dependencies,
    extract_source_dependencies,
)
from app.services.pipeline.pipeline_sql_safety_validator import validate_pipeline_model_sql
from app.services.runtime.run_registry import registry
from app.services.validation.validation_context import validation_context_from_dict
from app.utils.time import utcnow


PipelineStatus = Literal["not_ready", "not_run", "running", "completed", "failed"]
StepStatus = Literal["pending", "running", "completed", "failed"]
SourceDependency = tuple[str, str]


@dataclass
class PipelineModelArtifact:
    artifact_id: str
    filename: str
    model_name: str
    path: Path
    content: str
    dependencies: set[str]


class PipelineExecutionError(RuntimeError):
    pass


def get_pipeline_status(run_id: str) -> dict[str, Any]:
    _require_run(run_id)

    current = registry.runs[run_id].get("pipelineRun")
    if current:
        return current

    models = _collect_model_artifacts(run_id)
    status: PipelineStatus = "not_run" if models else "not_ready"

    return {
        "runId": run_id,
        "status": status,
        "martPath": str(_mart_path(run_id)),
        "startedAt": None,
        "completedAt": None,
        "models": [
            {
                "filename": model.filename,
                "modelName": model.model_name,
                "artifactId": model.artifact_id,
                "dependencies": sorted(model.dependencies),
                "status": "pending",
                "rowCount": None,
                "error": None,
            }
            for model in _sort_models(models)
        ],
        "tables": _list_mart_tables(run_id),
        "error": None,
    }


def execute_pipeline(run_id: str) -> dict[str, Any]:
    _require_run(run_id)

    models = _sort_models(_collect_model_artifacts(run_id))
    if not models:
        raise PipelineExecutionError(
            "No executable SQL model artifacts were found for this run. "
            "Generate dbt SQL model artifacts before running the demo pipeline."
        )

    pipeline_state = {
        "runId": run_id,
        "status": "running",
        "martPath": str(_mart_path(run_id)),
        "startedAt": utcnow(),
        "completedAt": None,
        "models": [
            {
                "filename": model.filename,
                "modelName": model.model_name,
                "artifactId": model.artifact_id,
                "dependencies": sorted(model.dependencies),
                "status": "pending",
                "rowCount": None,
                "error": None,
            }
            for model in models
        ],
        "tables": [],
        "error": None,
    }
    registry.runs[run_id]["pipelineRun"] = pipeline_state

    try:
        mart_path = _reset_mart(run_id)
        source_path = get_database_path()
        source_table_mapping, allowed_source_dependencies = _build_pipeline_source_context(
            run_id=run_id,
            source_path=source_path,
        )
        known_model_names = {model.model_name for model in models}

        with sqlite3.connect(mart_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(f"ATTACH DATABASE ? AS {quote_identifier('source_db')}", (str(source_path),))

            for index, model in enumerate(models):
                step = pipeline_state["models"][index]
                step["status"] = "running"

                try:
                    compiled_sql = compile_dbt_sql_to_sqlite(
                        model.content,
                        source_table_mapping=source_table_mapping,
                        allowed_source_dependencies=allowed_source_dependencies,
                        known_model_names=known_model_names,
                    )
                    validate_pipeline_model_sql(compiled_sql)

                    conn.execute(f"DROP TABLE IF EXISTS {quote_identifier(model.model_name)}")
                    conn.execute(
                        f"CREATE TABLE {quote_identifier(model.model_name)} AS\n{compiled_sql}"
                    )
                    row = conn.execute(
                        f"SELECT COUNT(*) AS row_count FROM {quote_identifier(model.model_name)}"
                    ).fetchone()

                    step["status"] = "completed"
                    step["rowCount"] = int(row["row_count"] if row else 0)
                except Exception as exc:
                    step["status"] = "failed"
                    step["error"] = str(exc)
                    raise

            conn.commit()

        pipeline_state["status"] = "completed"
        pipeline_state["completedAt"] = utcnow()
        pipeline_state["tables"] = _list_mart_tables(run_id)
        _write_pipeline_state(run_id, pipeline_state)
        return pipeline_state
    except Exception as exc:
        pipeline_state["status"] = "failed"
        pipeline_state["completedAt"] = utcnow()
        pipeline_state["error"] = str(exc)
        pipeline_state["tables"] = _list_mart_tables(run_id)
        _write_pipeline_state(run_id, pipeline_state)
        return pipeline_state


def preview_table(run_id: str, table_name: str, limit: int = 50) -> dict[str, Any]:
    _require_run(run_id)
    _validate_table_name(run_id, table_name)

    safe_limit = max(1, min(int(limit), 200))
    mart_path = _mart_path(run_id)

    if not mart_path.exists():
        raise FileNotFoundError("Demo mart has not been created yet. Run the pipeline first.")

    with sqlite3.connect(mart_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {quote_identifier(table_name)} LIMIT ?",
            (safe_limit,),
        ).fetchall()
        count_row = conn.execute(
            f"SELECT COUNT(*) AS row_count FROM {quote_identifier(table_name)}"
        ).fetchone()

    data = [dict(row) for row in rows]
    columns = list(data[0].keys()) if data else _table_columns(run_id, table_name)

    return {
        "runId": run_id,
        "tableName": table_name,
        "columns": columns,
        "rows": data,
        "rowCount": int(count_row["row_count"] if count_row else 0),
        "limit": safe_limit,
    }


def table_csv_bytes(run_id: str, table_name: str) -> bytes:
    _require_run(run_id)
    _validate_table_name(run_id, table_name)

    mart_path = _mart_path(run_id)
    with sqlite3.connect(mart_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {quote_identifier(table_name)}").fetchall()

    data = [dict(row) for row in rows]
    columns = list(data[0].keys()) if data else _table_columns(run_id, table_name)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue().encode("utf-8")


def all_tables_zip_bytes(run_id: str) -> bytes:
    _require_run(run_id)
    tables = _list_mart_tables(run_id)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table in tables:
            archive.writestr(f"{table['tableName']}.csv", table_csv_bytes(run_id, table["tableName"]))

        archive.writestr(
            "pipeline_run.json",
            json.dumps(get_pipeline_status(run_id), ensure_ascii=False, indent=2, default=str),
        )

    return buffer.getvalue()


def _require_run(run_id: str) -> None:
    if not registry.exists(run_id):
        raise FileNotFoundError("Run not found")


def _mart_root() -> Path:
    root = Path("/app/data/marts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _mart_dir(run_id: str) -> Path:
    safe_run_id = _safe_run_id(run_id)
    return _mart_root() / safe_run_id


def _mart_path(run_id: str) -> Path:
    return _mart_dir(run_id) / "demo_mart.db"


def _reset_mart(run_id: str) -> Path:
    mart_dir = _mart_dir(run_id)
    if mart_dir.exists():
        shutil.rmtree(mart_dir)
    mart_dir.mkdir(parents=True, exist_ok=True)
    return _mart_path(run_id)


def _write_pipeline_state(run_id: str, pipeline_state: dict[str, Any]) -> None:
    mart_dir = _mart_dir(run_id)
    mart_dir.mkdir(parents=True, exist_ok=True)
    (mart_dir / "pipeline_run.json").write_text(
        json.dumps(pipeline_state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_run_id(run_id: str) -> str:
    if not re.match(r"^[A-Za-z0-9_\-]+$", run_id):
        raise ValueError(f"Unsafe run id: {run_id}")
    return run_id


def _collect_model_artifacts(run_id: str) -> list[PipelineModelArtifact]:
    run = registry.runs[run_id]
    artifacts = run.get("artifacts", {})
    artifact_plan = run.get("artifactPlan", {}) or {}
    planned_model_files = set(str(item) for item in artifact_plan.get("model_files", []) if str(item).strip())

    models: list[PipelineModelArtifact] = []

    for artifact_id, artifact in artifacts.items():
        filename = str(artifact.get("filename", ""))
        artifact_type = str(artifact.get("type", ""))
        if artifact_type != "sql" or not filename.endswith(".sql"):
            continue

        if planned_model_files:
            if filename not in planned_model_files:
                continue
        elif _looks_like_test_or_direct_query(filename):
            continue

        path = Path(str(artifact.get("path", "")))
        if not path.exists():
            continue

        content = path.read_text(encoding="utf-8")
        model_name = Path(filename).stem
        models.append(
            PipelineModelArtifact(
                artifact_id=str(artifact_id),
                filename=filename,
                model_name=model_name,
                path=path,
                content=content,
                dependencies=extract_ref_dependencies(content),
            )
        )

    return models


def _looks_like_test_or_direct_query(filename: str) -> bool:
    normalized = filename.replace("\\", "/").lower()
    return (
        normalized.startswith("custom_tests/")
        or "/custom_tests/" in normalized
        or Path(normalized).name.startswith("test_")
        or normalized in {"analytics_query.sql"}
    )


def _sort_models(models: list[PipelineModelArtifact]) -> list[PipelineModelArtifact]:
    if not models:
        return []

    by_name = {model.model_name: model for model in models}
    visited: set[str] = set()
    visiting: set[str] = set()
    sorted_models: list[PipelineModelArtifact] = []

    def visit(model: PipelineModelArtifact) -> None:
        if model.model_name in visited:
            return
        if model.model_name in visiting:
            raise PipelineExecutionError(f"Circular model dependency detected at {model.model_name}")

        visiting.add(model.model_name)
        for dependency in sorted(model.dependencies):
            dependency_model = by_name.get(dependency)
            if dependency_model:
                visit(dependency_model)
        visiting.remove(model.model_name)
        visited.add(model.model_name)
        sorted_models.append(model)

    for model in sorted(models, key=_model_sort_key):
        visit(model)

    return sorted_models


def _model_sort_key(model: PipelineModelArtifact) -> tuple[int, str]:
    name = model.model_name
    if name.startswith("stg_"):
        tier = 0
    elif name.startswith("int_"):
        tier = 1
    elif name.startswith("mart_"):
        tier = 2
    else:
        tier = 3
    return tier, name


def _build_pipeline_source_context(
    *,
    run_id: str,
    source_path: Path,
) -> tuple[dict[str, str], set[SourceDependency]]:
    source_tables = _list_source_database_tables(source_path)
    run = registry.runs[run_id]

    selected_source_tables = _collect_selected_source_tables(run)
    declared_source_dependencies = _collect_declared_source_dependencies(run)

    validation_context = validation_context_from_dict(run.get("validationContext"))
    if validation_context:
        selected_source_tables.update(validation_context.selected_source_names)
        declared_source_dependencies.update(validation_context.allowed_source_dependencies)

    for source_table in selected_source_tables:
        if source_table in source_tables:
            declared_source_dependencies.update(_infer_source_dependencies_for_table(source_table))

    source_table_mapping: dict[str, str] = dict(validation_context.source_table_mapping) if validation_context else {}
    allowed_source_dependencies: set[SourceDependency] = set()

    for dependency in declared_source_dependencies:
        physical_table = _resolve_source_dependency_to_existing_table(
            dependency=dependency,
            source_tables=source_tables,
        )
        if not physical_table:
            continue

        allowed_source_dependencies.add(dependency)
        _add_source_mapping_candidates(
            mapping=source_table_mapping,
            dependency=dependency,
            physical_table=physical_table,
        )

    return source_table_mapping, allowed_source_dependencies


def _list_source_database_tables(source_path: Path) -> set[str]:
    if not source_path.exists():
        return set()

    with sqlite3.connect(source_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

    return {str(row["name"]) for row in rows}


def _collect_selected_source_tables(run: dict[str, Any]) -> set[str]:
    selected: set[str] = set()

    selected_source = run.get("selectedSource")
    if isinstance(selected_source, dict):
        source_name = selected_source.get("source_name")
        if source_name:
            selected.add(str(source_name))

    source_profile = run.get("sourceProfile")
    if isinstance(source_profile, dict):
        source_name = source_profile.get("source")
        if source_name:
            selected.add(str(source_name))

        selection = source_profile.get("selection")
        if isinstance(selection, dict):
            for source in selection.get("sources", []) or []:
                if source:
                    selected.add(str(source))

    selected_data_product = run.get("selectedDataProduct")
    if isinstance(selected_data_product, dict):
        for source in selected_data_product.get("sources", []) or []:
            if source:
                selected.add(str(source))

        selection = selected_data_product.get("selection")
        if isinstance(selection, dict):
            for source in selection.get("sources", []) or []:
                if source:
                    selected.add(str(source))

    return selected


def _collect_declared_source_dependencies(run: dict[str, Any]) -> set[SourceDependency]:
    declared: set[SourceDependency] = set()
    artifacts = run.get("artifacts", {})

    for artifact in artifacts.values():
        filename = str(artifact.get("filename", "")).lower()
        artifact_type = str(artifact.get("type", "")).lower()

        if artifact_type == "sql":
            continue

        if not (
            filename.endswith(".md")
            or filename.endswith(".yml")
            or filename.endswith(".yaml")
            or "source_profile" in filename
            or "relationship_profile" in filename
            or "join_plan" in filename
            or "data_quality_report" in filename
        ):
            continue

        content = _read_artifact_text(artifact)
        if content:
            declared.update(extract_source_dependencies(content))

    return declared


def _read_artifact_text(artifact: dict[str, Any]) -> str:
    for key in ("content", "contentPreview"):
        value = artifact.get(key)
        if isinstance(value, str) and value.strip():
            return value

    path_value = artifact.get("path")
    if not path_value:
        return ""

    path = Path(str(path_value))
    if not path.exists() or not path.is_file():
        return ""

    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _infer_source_dependencies_for_table(table_name: str) -> set[SourceDependency]:
    dependencies: set[SourceDependency] = set()
    clean_table = str(table_name).strip()

    if not clean_table:
        return dependencies

    dependencies.add((clean_table, clean_table))

    if "_" in clean_table:
        namespace, suffix = clean_table.split("_", 1)
        if namespace and suffix:
            dependencies.add((namespace, suffix))
            dependencies.add((namespace, clean_table))
            dependencies.add((clean_table, suffix))

    return dependencies


def _resolve_source_dependency_to_existing_table(
    *,
    dependency: SourceDependency,
    source_tables: set[str],
) -> str | None:
    source_name, table_name = dependency

    candidates = [
        table_name,
        f"{source_name}_{table_name}",
        f"{source_name}__{table_name}",
        source_name,
    ]

    for candidate in candidates:
        if candidate in source_tables:
            return candidate

    return None


def _add_source_mapping_candidates(
    *,
    mapping: dict[str, str],
    dependency: SourceDependency,
    physical_table: str,
) -> None:
    source_name, table_name = dependency

    candidates = [
        f"{source_name}.{table_name}",
        f"{source_name}.{_normalize_table_suffix(table_name)}",
        f"{source_name}.{source_name}_{table_name}",
        table_name,
        f"{source_name}_{table_name}",
        f"{source_name}__{table_name}",
        source_name,
    ]

    for candidate in candidates:
        mapping.setdefault(candidate, f"source_db.{physical_table}")


def _normalize_table_suffix(table_name: str) -> str:
    if table_name.startswith("stg_"):
        return table_name.removeprefix("stg_")
    if table_name.startswith("dim_"):
        return table_name.removeprefix("dim_")
    if table_name.startswith("fact_"):
        return table_name.removeprefix("fact_")
    return table_name


def _list_mart_tables(run_id: str) -> list[dict[str, Any]]:
    mart_path = _mart_path(run_id)
    if not mart_path.exists():
        return []

    with sqlite3.connect(mart_path) as conn:
        conn.row_factory = sqlite3.Row
        table_rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        tables: list[dict[str, Any]] = []
        for table_row in table_rows:
            table_name = table_row["name"]
            count_row = conn.execute(
                f"SELECT COUNT(*) AS row_count FROM {quote_identifier(table_name)}"
            ).fetchone()
            columns = [
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
            ]
            tables.append(
                {
                    "tableName": table_name,
                    "rowCount": int(count_row["row_count"] if count_row else 0),
                    "columns": columns,
                }
            )

    return tables


def _validate_table_name(run_id: str, table_name: str) -> None:
    quote_identifier(table_name)
    available = {table["tableName"] for table in _list_mart_tables(run_id)}
    if table_name not in available:
        raise FileNotFoundError(f"Table not found in demo mart: {table_name}")


def _table_columns(run_id: str, table_name: str) -> list[str]:
    mart_path = _mart_path(run_id)
    with sqlite3.connect(mart_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()
        ]
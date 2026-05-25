from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


class DbtSqlCompileError(ValueError):
    pass


_JINJA_CONFIG_PATTERN = re.compile(
    r"\{\{\s*config\s*\([^}]*\)\s*\}\}",
    flags=re.IGNORECASE | re.DOTALL,
)

_JINJA_COMMENT_PATTERN = re.compile(
    r"\{#.*?#\}",
    flags=re.DOTALL,
)

_JINJA_SOURCE_PATTERN = re.compile(
    r"\{\{\s*source\s*\(\s*(['\"])(?P<source>[^'\"]+)\1\s*,\s*(['\"])(?P<table>[^'\"]+)\3\s*\)\s*\}\}",
    flags=re.IGNORECASE,
)

_BARE_SOURCE_PATTERN = re.compile(
    r"(?<![\w.])source\s*\(\s*(['\"])(?P<source>[^'\"]+)\1\s*,\s*(['\"])(?P<table>[^'\"]+)\3\s*\)",
    flags=re.IGNORECASE,
)

_JINJA_REF_PATTERN = re.compile(
    r"\{\{\s*ref\s*\(\s*(['\"])(?P<model>[^'\"]+)\1\s*\)\s*\}\}",
    flags=re.IGNORECASE,
)

_BARE_REF_PATTERN = re.compile(
    r"(?<![\w.])ref\s*\(\s*(['\"])(?P<model>[^'\"]+)\1\s*\)",
    flags=re.IGNORECASE,
)

_UNSUPPORTED_JINJA_PATTERN = re.compile(
    r"(\{\{|\}\}|\{%|%\})",
)


SourceDependency = tuple[str, str]


def compile_dbt_sql_to_sqlite(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    """
    Compatibility entrypoint used by pipeline_executor.py.

    It compiles a small dbt-style SQL subset into SQLite-executable SQL.

    Supported:
    - {{ source('stripe', 'payments') }}
    - source('stripe', 'payments')
    - {{ ref('stg_stripe__payments') }}
    - ref('stg_stripe__payments')
    - {{ config(...) }}
    - {# jinja comments #}

    If allowed_source_dependencies is provided, every source() reference must be
    present in that whitelist. This prevents generated models from inventing
    unavailable sources such as source('fx', 'fx_rates').
    """
    effective_source_mapping = source_table_mapping or source_table_map
    effective_allowed_sources = allowed_source_dependencies
    if effective_allowed_sources is None:
        effective_allowed_sources = allowed_sources

    _validate_source_dependencies_against_whitelist(
        sql=sql,
        allowed_source_dependencies=effective_allowed_sources,
    )

    return compile_dbt_sql(
        sql,
        source_table_mapping=effective_source_mapping,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def extract_ref_dependencies(sql: str) -> list[str]:
    """
    Extract dbt model dependencies from both valid Jinja ref() and bare ref().

    Examples:
    - {{ ref('stg_stripe__payments') }}
    - ref('stg_stripe__payments')

    Returns unique model names in first-seen order.
    """
    if not sql:
        return []

    dependencies: list[str] = []
    seen: set[str] = set()

    for pattern in (_JINJA_REF_PATTERN, _BARE_REF_PATTERN):
        for match in pattern.finditer(sql):
            model_name = _clean_identifier_text(match.group("model"))

            if model_name and model_name not in seen:
                dependencies.append(model_name)
                seen.add(model_name)

    return dependencies


def extract_source_dependencies(sql: str) -> list[SourceDependency]:
    """
    Extract source dependencies from both valid Jinja source() and bare source().

    Examples:
    - {{ source('stripe', 'payments') }}
    - source('stripe', 'payments')
    """
    if not sql:
        return []

    dependencies: list[SourceDependency] = []
    seen: set[SourceDependency] = set()

    for pattern in (_JINJA_SOURCE_PATTERN, _BARE_SOURCE_PATTERN):
        for match in pattern.finditer(sql):
            source_name = _clean_identifier_text(match.group("source"))
            table_name = _clean_identifier_text(match.group("table"))
            dependency = (source_name, table_name)

            if source_name and table_name and dependency not in seen:
                dependencies.append(dependency)
                seen.add(dependency)

    return dependencies


def compile_dbt_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **_: Any,
) -> str:
    """
    Compile a small dbt-style SQL subset into SQLite-executable SQL.

    Supported dbt-like constructs:
    - {{ source('source_name', 'table_name') }}
    - source('source_name', 'table_name')
    - {{ ref('model_name') }}
    - ref('model_name')
    - {{ config(...) }}
    - {# jinja comments #}

    Bare source()/ref() support is intentional because LLM-generated dbt artifacts
    sometimes omit {{ }} around macros. The compiler treats that as recoverable
    instead of letting SQLite fail with "no such table: source" or "no such table: ref".
    """
    if not sql or not sql.strip():
        raise DbtSqlCompileError("Cannot compile empty dbt SQL.")

    effective_source_mapping = source_table_mapping or source_table_map

    compiled = sql

    compiled = _JINJA_COMMENT_PATTERN.sub("", compiled)
    compiled = _JINJA_CONFIG_PATTERN.sub("", compiled)

    all_known_models = _merge_known_model_names(
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
    )

    compiled = _JINJA_SOURCE_PATTERN.sub(
        lambda match: _quote_identifier(
            _resolve_source_table(
                source_name=match.group("source"),
                table_name=match.group("table"),
                source_table_mapping=effective_source_mapping,
            )
        ),
        compiled,
    )

    compiled = _BARE_SOURCE_PATTERN.sub(
        lambda match: _quote_identifier(
            _resolve_source_table(
                source_name=match.group("source"),
                table_name=match.group("table"),
                source_table_mapping=effective_source_mapping,
            )
        ),
        compiled,
    )

    compiled = _JINJA_REF_PATTERN.sub(
        lambda match: _quote_identifier(
            _resolve_ref_table(
                model_name=match.group("model"),
                known_model_names=all_known_models,
            )
        ),
        compiled,
    )

    compiled = _BARE_REF_PATTERN.sub(
        lambda match: _quote_identifier(
            _resolve_ref_table(
                model_name=match.group("model"),
                known_model_names=all_known_models,
            )
        ),
        compiled,
    )

    if _UNSUPPORTED_JINJA_PATTERN.search(compiled):
        raise DbtSqlCompileError(
            "Unsupported Jinja/dbt syntax remains after compilation. "
            "Only source(), ref(), config(), and Jinja comments are supported by the demo executor."
        )

    return _strip_trailing_semicolon(compiled).strip()


def compile_pipeline_model_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    return compile_dbt_sql_to_sqlite(
        sql,
        source_table_mapping=source_table_mapping,
        source_table_map=source_table_map,
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_sources=allowed_sources,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def compile_dbt_model_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    return compile_dbt_sql_to_sqlite(
        sql,
        source_table_mapping=source_table_mapping,
        source_table_map=source_table_map,
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_sources=allowed_sources,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def compile_pipeline_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    return compile_dbt_sql_to_sqlite(
        sql,
        source_table_mapping=source_table_mapping,
        source_table_map=source_table_map,
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_sources=allowed_sources,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def compile_model_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    return compile_dbt_sql_to_sqlite(
        sql,
        source_table_mapping=source_table_mapping,
        source_table_map=source_table_map,
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_sources=allowed_sources,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def compile_sql(
    sql: str,
    *,
    source_table_mapping: Mapping[str, str] | None = None,
    source_table_map: Mapping[str, str] | None = None,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None = None,
    allowed_sources: Iterable[SourceDependency | str] | None = None,
    known_model_names: Iterable[str] | None = None,
    model_names: Iterable[str] | None = None,
    materialized_tables: Iterable[str] | None = None,
    **kwargs: Any,
) -> str:
    return compile_dbt_sql_to_sqlite(
        sql,
        source_table_mapping=source_table_mapping,
        source_table_map=source_table_map,
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_sources=allowed_sources,
        known_model_names=known_model_names,
        model_names=model_names,
        materialized_tables=materialized_tables,
        **kwargs,
    )


def _validate_source_dependencies_against_whitelist(
    *,
    sql: str,
    allowed_source_dependencies: Iterable[SourceDependency | str] | None,
) -> None:
    if allowed_source_dependencies is None:
        return

    allowed = _normalize_allowed_source_dependencies(allowed_source_dependencies)
    dependencies = extract_source_dependencies(sql)

    if not dependencies:
        return

    unavailable = [dependency for dependency in dependencies if dependency not in allowed]

    if not unavailable:
        return

    unavailable_text = ", ".join(_format_source_dependency(dependency) for dependency in unavailable)
    allowed_text = (
        ", ".join(_format_source_dependency(dependency) for dependency in sorted(allowed))
        if allowed
        else "none"
    )

    raise DbtSqlCompileError(
        "Generated model references unavailable source(s): "
        f"{unavailable_text}. "
        f"Available sources for this run: {allowed_text}. "
        "This is likely a model-generation hallucination or a missing source configuration."
    )


def _normalize_allowed_source_dependencies(
    values: Iterable[SourceDependency | str],
) -> set[SourceDependency]:
    normalized: set[SourceDependency] = set()

    for value in values:
        if isinstance(value, tuple) and len(value) == 2:
            source_name, table_name = value
            source_name = _clean_identifier_text(str(source_name))
            table_name = _clean_identifier_text(str(table_name))
            if source_name and table_name:
                normalized.add((source_name, table_name))
            continue

        if isinstance(value, list) and len(value) == 2:
            source_name, table_name = value
            source_name = _clean_identifier_text(str(source_name))
            table_name = _clean_identifier_text(str(table_name))
            if source_name and table_name:
                normalized.add((source_name, table_name))
            continue

        if isinstance(value, str):
            parsed = _parse_source_dependency_string(value)
            if parsed:
                normalized.add(parsed)

    return normalized


def _parse_source_dependency_string(value: str) -> SourceDependency | None:
    value = value.strip()

    for pattern in (_JINJA_SOURCE_PATTERN, _BARE_SOURCE_PATTERN):
        match = pattern.search(value)
        if match:
            return (
                _clean_identifier_text(match.group("source")),
                _clean_identifier_text(match.group("table")),
            )

    if "." in value:
        source_name, table_name = value.split(".", 1)
        source_name = _clean_identifier_text(source_name)
        table_name = _clean_identifier_text(table_name)
        if source_name and table_name:
            return source_name, table_name

    return None


def _format_source_dependency(dependency: SourceDependency) -> str:
    source_name, table_name = dependency
    return f"source('{source_name}', '{table_name}')"


def _merge_known_model_names(
    *,
    known_model_names: Iterable[str] | None,
    model_names: Iterable[str] | None,
    materialized_tables: Iterable[str] | None,
) -> set[str]:
    merged: set[str] = set()

    for values in (known_model_names, model_names, materialized_tables):
        if not values:
            continue

        for value in values:
            if value:
                merged.add(str(value))

    return merged


def _resolve_source_table(
    *,
    source_name: str,
    table_name: str,
    source_table_mapping: Mapping[str, str] | None,
) -> str:
    source_name = _clean_identifier_text(source_name)
    table_name = _clean_identifier_text(table_name)

    if not source_name or not table_name:
        raise DbtSqlCompileError("source() requires both source name and table name.")

    mapping_candidates = [
        f"{source_name}.{table_name}",
        f"{source_name}.{_normalize_table_suffix(table_name)}",
        f"{source_name}.{source_name}_{table_name}",
        table_name,
        f"{source_name}_{table_name}",
        f"{source_name}__{table_name}",
        source_name,
    ]

    if source_table_mapping:
        normalized_mapping = {
            str(key).strip(): str(value).strip()
            for key, value in source_table_mapping.items()
            if key and value
        }

        for candidate in mapping_candidates:
            if candidate in normalized_mapping:
                return normalized_mapping[candidate]

    if source_name == table_name:
        return table_name

    if source_name.endswith(f"_{table_name}") or source_name.endswith(f"__{table_name}"):
        return source_name

    if _looks_like_physical_table_name(table_name):
        return table_name

    return f"{source_name}_{table_name}"


def _resolve_ref_table(
    *,
    model_name: str,
    known_model_names: set[str],
) -> str:
    model_name = _clean_identifier_text(model_name)

    if not model_name:
        raise DbtSqlCompileError("ref() requires a model name.")

    if known_model_names and model_name not in known_model_names:
        # Keep permissive. If dependency ordering is wrong, SQLite will fail clearly
        # with a missing-table error during execution.
        return model_name

    return model_name


def _clean_identifier_text(value: str) -> str:
    return str(value).strip().strip("`").strip('"').strip("'")


def _normalize_table_suffix(table_name: str) -> str:
    if table_name.startswith("stg_"):
        return table_name.removeprefix("stg_")
    if table_name.startswith("dim_"):
        return table_name.removeprefix("dim_")
    if table_name.startswith("fact_"):
        return table_name.removeprefix("fact_")
    return table_name


def _looks_like_physical_table_name(table_name: str) -> bool:
    physical_prefixes = (
        "dim_",
        "fact_",
        "stripe_",
        "raw_",
        "src_",
    )

    return table_name.startswith(physical_prefixes)


def _quote_identifier(identifier: str) -> str:
    identifier = identifier.strip()

    if not identifier:
        raise DbtSqlCompileError("Cannot quote empty SQL identifier.")

    if "." in identifier:
        return ".".join(_quote_identifier(part) for part in identifier.split("."))

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        return identifier

    return '"' + identifier.replace('"', '""') + '"'


def _strip_trailing_semicolon(sql: str) -> str:
    stripped = sql.rstrip()

    if not stripped.endswith(";"):
        return sql

    return stripped[:-1].rstrip()
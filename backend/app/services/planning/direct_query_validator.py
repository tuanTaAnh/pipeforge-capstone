from __future__ import annotations

import re
from typing import Any

from app.services.analytics.sql_safety_validator import validate_select_sql


class DirectQueryValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_direct_query_sql(
    *,
    sql: str,
    metadata_context: dict[str, Any],
    selected_sources: list[str],
) -> None:
    errors: list[str] = []

    try:
        validate_select_sql(sql)
    except Exception as exc:
        errors.append(str(exc))

    allowed_sources = set(selected_sources or metadata_context.get("allowed_sources", []))
    all_sources = set(metadata_context.get("allowed_sources", []))
    normalized = _strip_string_literals(sql)

    cte_names = _extract_cte_names(normalized)
    referenced_tables = _extract_tables(normalized)
    for table in referenced_tables:
        if table in cte_names:
            continue
        if table in all_sources and table not in allowed_sources:
            errors.append(f"SQL references table `{table}` outside selected sources {sorted(allowed_sources)}")
        elif table not in all_sources:
            errors.append(f"SQL references unknown table `{table}`")

    alias_to_table = _extract_table_aliases(normalized)
    sources = metadata_context.get("sources", {})

    for alias, column in _extract_qualified_columns(normalized):
        table = alias_to_table.get(alias, alias)
        if table not in sources:
            # SQLite functions or CTE aliases can look like qualifiers; keep this as a soft validation.
            continue
        if column not in sources[table].get("columns", {}):
            errors.append(f"SQL references unknown column `{table}.{column}`")

    for source_name in all_sources:
        if source_name in normalized and source_name not in allowed_sources:
            errors.append(f"SQL text contains non-selected source `{source_name}`")

    if errors:
        raise DirectQueryValidationError(sorted(set(errors)))


def _strip_string_literals(sql: str) -> str:
    return re.sub(r"'([^']|'')*'", "''", sql)


def _extract_tables(sql: str) -> set[str]:
    tables: set[str] = set()
    for match in re.finditer(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", sql, flags=re.IGNORECASE):
        tables.add(match.group(1))
    return tables


def _extract_table_aliases(sql: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    pattern = re.compile(
        r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    reserved = {"where", "on", "left", "right", "inner", "outer", "join", "group", "order", "limit"}
    for match in pattern.finditer(sql):
        table = match.group(1)
        alias = match.group(2)
        aliases[table] = table
        if alias and alias.lower() not in reserved:
            aliases[alias] = table
    return aliases


def _extract_qualified_columns(sql: str) -> set[tuple[str, str]]:
    return {
        (match.group(1), match.group(2))
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", sql)
    }


def _extract_cte_names(sql: str) -> set[str]:
    if not re.match(r"\s*with\b", sql, flags=re.IGNORECASE):
        return set()
    return {
        match.group(1)
        for match in re.finditer(r"(?:with|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", sql, flags=re.IGNORECASE)
    }

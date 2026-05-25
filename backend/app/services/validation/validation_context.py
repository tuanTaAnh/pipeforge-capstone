from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.services.metadata.contract_loader import get_contract_columns, get_contract_dbt_source, get_contract_source_name, load_source_contract

SourceDependency = tuple[str, str]

_SOURCE_RE = re.compile(
    r"source\s*\(\s*(['\"])(?P<source>[^'\"]+)\1\s*,\s*(['\"])(?P<table>[^'\"]+)\3\s*\)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationContext:
    """Single source of truth for source/model validation during one run.

    This context is built from selected source contracts, not from generated
    artifacts. It prevents different modules from inventing their own source
    whitelist and drifting out of sync.
    """

    selected_source_names: list[str]
    allowed_source_dependencies: set[SourceDependency]
    allowed_source_refs: list[str]
    allowed_columns_by_source: dict[str, list[str]]
    source_table_mapping: dict[str, str] = field(default_factory=dict)
    expected_model_files: list[str] = field(default_factory=list)
    expected_test_files: list[str] = field(default_factory=list)
    expected_documentation_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_source_names": list(self.selected_source_names),
            "allowed_source_dependencies": [list(item) for item in sorted(self.allowed_source_dependencies)],
            "allowed_source_refs": list(self.allowed_source_refs),
            "allowed_columns_by_source": dict(self.allowed_columns_by_source),
            "source_table_mapping": dict(self.source_table_mapping),
            "expected_model_files": list(self.expected_model_files),
            "expected_test_files": list(self.expected_test_files),
            "expected_documentation_files": list(self.expected_documentation_files),
        }

    def prompt_context(self) -> str:
        lines: list[str] = [
            "Allowed raw source refs for this run:",
        ]
        for source_ref in self.allowed_source_refs:
            lines.append(f"- {{{{ {source_ref} }}}}")

        lines.extend(["", "Allowed columns by source:"])
        for source_name, columns in self.allowed_columns_by_source.items():
            column_text = ", ".join(columns) if columns else "(none listed)"
            lines.append(f"- {source_name}: {column_text}")

        lines.extend(
            [
                "",
                "Validation rules:",
                "- Use only the raw source refs listed above.",
                "- Use only the columns listed above for each source.",
                "- Do not infer allowed sources from files already generated.",
                "- Do not invent physical table names, lookup tables, FX tables, or calendar/date-spine tables.",
            ]
        )
        return "\n".join(lines)


def build_validation_context_from_contracts(
    *,
    selected_contracts: dict[str, dict[str, Any]],
    artifact_plan: dict[str, Any] | None = None,
) -> ValidationContext:
    artifact_plan = artifact_plan or {}

    selected_source_names: list[str] = []
    allowed_source_dependencies: set[SourceDependency] = set()
    allowed_source_refs: list[str] = []
    allowed_columns_by_source: dict[str, list[str]] = {}
    source_table_mapping: dict[str, str] = {}

    for fallback_name, contract in selected_contracts.items():
        source_name = get_contract_source_name(contract) if contract else str(fallback_name)
        dbt_source = get_contract_dbt_source(contract)
        dependency = parse_source_dependency(dbt_source) or ("demo", source_name)
        columns = list(get_contract_columns(contract).keys())
        physical_table = source_name

        selected_source_names.append(source_name)
        allowed_source_dependencies.add(dependency)
        allowed_source_refs.append(format_source_ref(dependency))
        allowed_columns_by_source[source_name] = columns

        _add_source_mapping_candidates(source_table_mapping, dependency, physical_table)
        # Also allow the logical source name as a fallback key for demo execution.
        source_table_mapping.setdefault(source_name, physical_table)
        source_table_mapping.setdefault(physical_table, physical_table)

    return ValidationContext(
        selected_source_names=sorted(set(selected_source_names)),
        allowed_source_dependencies=allowed_source_dependencies,
        allowed_source_refs=sorted(set(allowed_source_refs)),
        allowed_columns_by_source={key: allowed_columns_by_source[key] for key in sorted(allowed_columns_by_source)},
        source_table_mapping=source_table_mapping,
        expected_model_files=_as_list(artifact_plan.get("model_files")),
        expected_test_files=_as_list(artifact_plan.get("test_files")),
        expected_documentation_files=_as_list(artifact_plan.get("documentation_files")),
    )


def build_validation_context_from_sources(
    *,
    selected_sources: Iterable[str],
    artifact_plan: dict[str, Any] | None = None,
) -> ValidationContext:
    contracts: dict[str, dict[str, Any]] = {}
    for source_name in selected_sources:
        source_name = str(source_name).strip()
        if not source_name:
            continue
        contracts[source_name] = load_source_contract(source_name)
    return build_validation_context_from_contracts(selected_contracts=contracts, artifact_plan=artifact_plan)


def validation_context_from_dict(value: dict[str, Any] | None) -> ValidationContext | None:
    if not isinstance(value, dict):
        return None
    deps: set[SourceDependency] = set()
    for item in value.get("allowed_source_dependencies", []) or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            deps.add((str(item[0]), str(item[1])))
    return ValidationContext(
        selected_source_names=[str(item) for item in value.get("selected_source_names", []) or []],
        allowed_source_dependencies=deps,
        allowed_source_refs=[str(item) for item in value.get("allowed_source_refs", []) or []],
        allowed_columns_by_source={str(k): [str(col) for col in (v or [])] for k, v in (value.get("allowed_columns_by_source", {}) or {}).items()},
        source_table_mapping={str(k): str(v) for k, v in (value.get("source_table_mapping", {}) or {}).items()},
        expected_model_files=[str(item) for item in value.get("expected_model_files", []) or []],
        expected_test_files=[str(item) for item in value.get("expected_test_files", []) or []],
        expected_documentation_files=[str(item) for item in value.get("expected_documentation_files", []) or []],
    )


def parse_source_dependency(value: str) -> SourceDependency | None:
    match = _SOURCE_RE.search(str(value))
    if not match:
        return None
    return _clean_identifier(match.group("source")), _clean_identifier(match.group("table"))


def format_source_ref(dependency: SourceDependency) -> str:
    source_name, table_name = dependency
    return f"source('{source_name}', '{table_name}')"


def _add_source_mapping_candidates(mapping: dict[str, str], dependency: SourceDependency, physical_table: str) -> None:
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
        mapping.setdefault(candidate, physical_table)


def _normalize_table_suffix(table_name: str) -> str:
    if table_name.startswith("stg_"):
        return table_name.removeprefix("stg_")
    if table_name.startswith("dim_"):
        return table_name.removeprefix("dim_")
    if table_name.startswith("fact_"):
        return table_name.removeprefix("fact_")
    return table_name


def _clean_identifier(value: str) -> str:
    return str(value).strip().strip('`"\'')


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []

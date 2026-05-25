from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.paths import CONTRACTS_DIR


def list_source_contract_paths() -> list[Path]:
    """Return only per-source contracts.

    The contracts folder can also contain higher-level metadata files such as
    catalog.yml, relationships.yml, and data_products/*.yml. Those files are not
    source contracts and must not be loaded by the single-source selector.
    """
    if not CONTRACTS_DIR.exists():
        return []

    candidates = sorted(CONTRACTS_DIR.glob("*.yml")) + sorted(CONTRACTS_DIR.glob("*.yaml"))

    return [path for path in candidates if _is_source_contract_path(path)]


def _is_source_contract_path(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except Exception as exc:
        print(
            f"[PF WARNING][contract_loader] Could not inspect contract candidate {path}: {exc}",
            flush=True,
        )
        return False

    if not isinstance(data, dict):
        return False

    source = data.get("source")
    columns = data.get("columns")

    return isinstance(source, dict) and isinstance(columns, dict) and bool(source.get("name"))


def list_source_contract_names() -> list[str]:
    names: list[str] = []

    for path in list_source_contract_paths():
        try:
            contract = load_source_contract_from_path(path)
            names.append(get_contract_source_name(contract))
        except Exception as exc:
            print(
                f"[PF WARNING][contract_loader] Failed to load contract {path}: {exc}",
                flush=True,
            )

    return sorted(set(names))


def load_all_source_contracts() -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []

    for path in list_source_contract_paths():
        contract = load_source_contract_from_path(path)
        contracts.append(contract)

    return contracts


def load_source_contract(source_name: str) -> dict[str, Any]:
    candidates = [
        CONTRACTS_DIR / f"{source_name}.yml",
        CONTRACTS_DIR / f"{source_name}.yaml",
    ]

    for path in candidates:
        if path.exists():
            return load_source_contract_from_path(path)

    raise FileNotFoundError(
        f"Source contract not found for source={source_name}. "
        f"Looked in: {', '.join(str(path) for path in candidates)}"
    )


def load_source_contract_from_path(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Source contract must be a YAML object: {path}")

    _validate_contract(data, path)

    data["_contract_path"] = str(path)

    return data


def _validate_contract(contract: dict[str, Any], path: Path) -> None:
    source = contract.get("source")
    columns = contract.get("columns")

    if not isinstance(source, dict):
        raise ValueError(f"Contract source section is missing or invalid: {path}")

    if not source.get("name"):
        raise ValueError(f"Contract source.name is required: {path}")

    if not isinstance(columns, dict) or not columns:
        raise ValueError(f"Contract columns section is missing or invalid: {path}")

    for column_name, column_contract in columns.items():
        if not isinstance(column_contract, dict):
            raise ValueError(f"Column contract must be an object: {column_name}")

        if not column_contract.get("type"):
            raise ValueError(f"Column contract missing type: {column_name}")

        if "nullable" not in column_contract:
            raise ValueError(f"Column contract missing nullable flag: {column_name}")


def get_contract_columns(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    columns = contract.get("columns", {})

    if not isinstance(columns, dict):
        return {}

    return {
        str(column_name): column_contract
        for column_name, column_contract in columns.items()
        if isinstance(column_contract, dict)
    }


def get_contract_source_name(contract: dict[str, Any]) -> str:
    return str(contract["source"]["name"])


def get_contract_dbt_source(contract: dict[str, Any]) -> str:
    source = contract.get("source", {})

    if isinstance(source, dict) and source.get("dbt_source"):
        return str(source["dbt_source"])

    return f"source('{get_contract_source_name(contract)}')"


def get_contract_aliases(contract: dict[str, Any]) -> list[str]:
    source = contract.get("source", {})
    business_context = contract.get("business_context", {})

    aliases: list[str] = []

    source_name = get_contract_source_name(contract)
    aliases.append(source_name)
    aliases.append(source_name.replace("_", " "))

    if isinstance(source, dict):
        for key in ["description", "owner"]:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                aliases.append(value)

        raw_aliases = source.get("aliases", [])
        if isinstance(raw_aliases, list):
            aliases.extend(str(item) for item in raw_aliases if str(item).strip())

    if isinstance(business_context, dict):
        for key in [
            "data_product_goal",
            "final_mart",
            "metric_name",
        ]:
            value = business_context.get(key)
            if isinstance(value, str) and value.strip():
                aliases.append(value)

        for key in ["grain", "primary_metric_dimensions", "keywords"]:
            value = business_context.get(key)
            if isinstance(value, list):
                aliases.extend(str(item) for item in value if str(item).strip())

    return sorted(set(alias.strip() for alias in aliases if alias.strip()))


def get_artifact_plan(contract: dict[str, Any]) -> dict[str, Any]:
    source_name = get_contract_source_name(contract)
    business_context = contract.get("business_context", {})

    raw_plan = contract.get("artifact_plan", {})
    if not isinstance(raw_plan, dict):
        raw_plan = {}

    default_plan = build_default_artifact_plan(source_name, business_context)

    merged = {
        **default_plan,
        **raw_plan,
    }

    merged["model_files"] = _normalize_file_list(
        merged.get("model_files"),
        default_plan["model_files"],
    )
    merged["test_files"] = _normalize_file_list(
        merged.get("test_files"),
        default_plan["test_files"],
    )
    merged["documentation_files"] = _normalize_file_list(
        merged.get("documentation_files"),
        default_plan["documentation_files"],
    )

    if not merged.get("final_mart_name"):
        merged["final_mart_name"] = default_plan["final_mart_name"]

    return merged


def build_default_artifact_plan(
    source_name: str,
    business_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    business_context = business_context or {}

    namespace, object_name = _split_source_name(source_name)

    staging_model = f"stg_{namespace}__{object_name}"
    intermediate_model = f"int_{object_name}__rules"

    final_mart_name = business_context.get("final_mart")
    if not final_mart_name:
        final_mart_name = f"mart_{object_name}__summary"

    metric_name = business_context.get("metric_name", "primary_metric")
    custom_test_metric = str(metric_name).replace(" ", "_").lower()

    return {
        "package_name": f"{source_name} Data Product Draft",
        "source_name": source_name,
        "staging_model": staging_model,
        "intermediate_model": intermediate_model,
        "final_mart_name": final_mart_name,
        "model_files": [
            f"{staging_model}.sql",
            f"{intermediate_model}.sql",
            f"{final_mart_name}.sql",
        ],
        "test_files": [
            "schema.yml",
            f"custom_tests/test_{custom_test_metric}_not_null.sql",
        ],
        "documentation_files": [
            "pipeline_summary.md",
        ],
    }


def _split_source_name(source_name: str) -> tuple[str, str]:
    parts = source_name.split("_", 1)

    if len(parts) == 2:
        return parts[0], parts[1]

    return "source", source_name


def _normalize_file_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback

    cleaned = [str(item).strip() for item in value if str(item).strip()]

    return cleaned or fallback

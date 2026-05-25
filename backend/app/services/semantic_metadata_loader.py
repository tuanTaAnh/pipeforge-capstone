from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
DATA_PRODUCTS_DIR = CONTRACTS_DIR / "data_products"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Metadata file must contain a YAML object: {path}")

    data["_metadata_path"] = str(path)

    return data


def load_catalog() -> dict[str, Any]:
    return _load_yaml(CONTRACTS_DIR / "catalog.yml")


def load_relationships() -> dict[str, Any]:
    return _load_yaml(CONTRACTS_DIR / "relationships.yml")


def load_data_product_contracts() -> list[dict[str, Any]]:
    if not DATA_PRODUCTS_DIR.exists():
        return []

    contracts: list[dict[str, Any]] = []

    for path in sorted(DATA_PRODUCTS_DIR.glob("*.yml")) + sorted(DATA_PRODUCTS_DIR.glob("*.yaml")):
        contract = _load_yaml(path)
        _validate_data_product_contract(contract, path)
        contracts.append(contract)

    return contracts


def load_data_product_contract(name: str) -> dict[str, Any]:
    for contract in load_data_product_contracts():
        data_product = contract.get("data_product", {})
        if isinstance(data_product, dict) and data_product.get("name") == name:
            return contract

    raise FileNotFoundError(f"Data product contract not found: {name}")


def get_relationship_by_id(relationship_id: str) -> dict[str, Any]:
    relationships = load_relationships().get("relationships", [])

    if not isinstance(relationships, list):
        raise ValueError("relationships.yml must contain a relationships list.")

    for relationship in relationships:
        if isinstance(relationship, dict) and relationship.get("id") == relationship_id:
            return relationship

    raise FileNotFoundError(f"Relationship not found: {relationship_id}")


def get_relationships_for_sources(source_names: list[str]) -> list[dict[str, Any]]:
    source_set = set(source_names)
    relationships = load_relationships().get("relationships", [])

    if not isinstance(relationships, list):
        return []

    matching: list[dict[str, Any]] = []

    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue

        left_source = relationship.get("left_source")
        right_source = relationship.get("right_source")

        if left_source in source_set and right_source in source_set:
            matching.append(relationship)

    return matching


def get_catalog_source(source_name: str) -> dict[str, Any] | None:
    sources = load_catalog().get("sources", [])

    if not isinstance(sources, list):
        return None

    for source in sources:
        if isinstance(source, dict) and source.get("name") == source_name:
            return source

    return None


def get_data_product_artifact_plan(contract: dict[str, Any]) -> dict[str, Any]:
    data_product = contract.get("data_product", {})

    if not isinstance(data_product, dict):
        raise ValueError("Data product contract missing data_product section.")

    artifact_plan = data_product.get("artifact_plan", {})

    if not isinstance(artifact_plan, dict):
        raise ValueError("Data product contract missing data_product.artifact_plan section.")

    model_files = _normalize_file_list(artifact_plan.get("model_files"))
    test_files = _normalize_file_list(artifact_plan.get("test_files"))
    documentation_files = _normalize_file_list(artifact_plan.get("documentation_files"))

    return {
        **artifact_plan,
        "package_name": artifact_plan.get("package_name") or data_product.get("package_name"),
        "source_name": artifact_plan.get("source_name") or data_product.get("name"),
        "model_files": model_files,
        "test_files": test_files,
        "documentation_files": documentation_files,
    }


def _normalize_file_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def _validate_data_product_contract(contract: dict[str, Any], path: Path) -> None:
    data_product = contract.get("data_product")

    if not isinstance(data_product, dict):
        raise ValueError(f"Data product contract missing data_product section: {path}")

    for key in ["name", "sources", "relationships", "artifact_plan"]:
        if key not in data_product:
            raise ValueError(f"Data product contract missing data_product.{key}: {path}")

    if not isinstance(data_product["sources"], list) or not data_product["sources"]:
        raise ValueError(f"Data product sources must be a non-empty list: {path}")

    if not isinstance(data_product["relationships"], list) or not data_product["relationships"]:
        raise ValueError(f"Data product relationships must be a non-empty list: {path}")

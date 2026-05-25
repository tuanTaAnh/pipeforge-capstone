from __future__ import annotations

import json
from typing import Any

from app.services.metadata.contract_loader import (
    get_contract_columns,
    get_contract_source_name,
    load_all_source_contracts,
    load_source_contract,
)
from app.services.metadata.semantic_layer_loader import load_dimensions, load_metrics, load_time_semantics
from app.services.metadata.semantic_metadata_loader import (
    get_relationships_for_sources,
    load_catalog,
    load_data_product_contracts,
    load_relationships,
)


def build_metadata_context() -> dict[str, Any]:
    """Build a compact but complete metadata catalog for LLM planning and code validation."""
    source_contracts = load_all_source_contracts()
    metrics = load_metrics()
    dimensions = load_dimensions()
    time_semantics = load_time_semantics()
    data_products = load_data_product_contracts()

    sources: dict[str, Any] = {}
    for contract in source_contracts:
        source_name = get_contract_source_name(contract)
        source = contract.get("source", {})
        columns = get_contract_columns(contract)
        sources[source_name] = {
            "name": source_name,
            "description": source.get("description"),
            "aliases": source.get("aliases", []),
            "dbt_source": source.get("dbt_source"),
            "business_context": contract.get("business_context", {}),
            "columns": {
                column_name: {
                    "type": column.get("type"),
                    "nullable": column.get("nullable"),
                    "description": column.get("description"),
                    "primary_key": column.get("primary_key", False),
                    "accepted_values": column.get("accepted_values"),
                }
                for column_name, column in columns.items()
            },
            "business_rules": contract.get("business_rules", []),
        }

    data_product_context: dict[str, Any] = {}
    for contract in data_products:
        data_product = contract.get("data_product", {})
        name = str(data_product.get("name", "")).strip()
        if not name:
            continue
        data_product_context[name] = {
            "name": name,
            "package_name": data_product.get("package_name"),
            "description": data_product.get("description"),
            "aliases": data_product.get("aliases", []),
            "sources": data_product.get("sources", []),
            "primary_source": data_product.get("primary_source"),
            "relationships": data_product.get("relationships", []),
            "grain": data_product.get("grain", []),
            "metrics": data_product.get("metrics", []),
            "known_business_questions": data_product.get("business_questions", []),
            "artifact_plan_examples": data_product.get("artifact_plan", {}),
        }

    relationships = load_relationships().get("relationships", [])
    if not isinstance(relationships, list):
        relationships = []

    known_limitations = _extract_known_limitations(metrics=metrics, sources=sources)

    return {
        "catalog": _safe_load_catalog(),
        "sources": sources,
        "metrics": metrics,
        "dimensions": dimensions,
        "time_semantics": time_semantics,
        "relationships": relationships,
        "data_products": data_product_context,
        "known_limitations": known_limitations,
        "allowed_sources": sorted(sources.keys()),
        "allowed_metrics": sorted(metrics.keys()),
        "allowed_dimensions": sorted(dimensions.keys()),
        "allowed_data_products": sorted(data_product_context.keys()),
    }


def build_llm_metadata_prompt_context(metadata_context: dict[str, Any], *, selected_sources: list[str] | None = None) -> str:
    """Render metadata context for prompts. Selected sources receive full detail; otherwise compact all-source context is used."""
    selected_sources = [source for source in selected_sources or [] if source in metadata_context.get("sources", {})]

    if selected_sources:
        sources = {source: metadata_context["sources"][source] for source in selected_sources}
        relationships = get_relationships_for_sources(selected_sources)
    else:
        sources = {
            source_name: {
                "name": source.get("name"),
                "description": source.get("description"),
                "aliases": source.get("aliases", []),
                "columns": {
                    column_name: {
                        "type": column.get("type"),
                        "description": column.get("description"),
                        "accepted_values": column.get("accepted_values"),
                    }
                    for column_name, column in source.get("columns", {}).items()
                },
                "business_context": source.get("business_context", {}),
            }
            for source_name, source in metadata_context.get("sources", {}).items()
        }
        relationships = metadata_context.get("relationships", [])

    prompt_context = {
        "sources": sources,
        "metrics": metadata_context.get("metrics", {}),
        "dimensions": metadata_context.get("dimensions", {}),
        "relationships": relationships,
        "data_products": metadata_context.get("data_products", {}),
        "known_limitations": metadata_context.get("known_limitations", []),
        "allowed_sources": metadata_context.get("allowed_sources", []),
        "allowed_metrics": metadata_context.get("allowed_metrics", []),
        "allowed_dimensions": metadata_context.get("allowed_dimensions", []),
        "allowed_data_products": metadata_context.get("allowed_data_products", []),
    }

    return json.dumps(prompt_context, ensure_ascii=False, indent=2, default=str)


def load_selected_contracts(selected_sources: list[str]) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for source_name in selected_sources:
        contracts[source_name] = load_source_contract(source_name)
    return contracts


def _safe_load_catalog() -> dict[str, Any]:
    try:
        return load_catalog()
    except Exception:
        return {}


def _extract_known_limitations(metrics: dict[str, Any], sources: dict[str, Any]) -> list[str]:
    limitations = [
        "Do not invent tables or columns that are not present in the metadata context.",
        "Do not perform FX conversion unless an explicit FX/source table or FX column is available.",
        "Preserve and group by currency when multiple currencies exist and no FX source is available.",
        "Direct analytics SQL must be read-only SELECT/WITH SQL.",
    ]

    has_fx_source = any("fx" in source_name.lower() or "exchange" in source_name.lower() for source_name in sources)
    if not has_fx_source:
        limitations.append("No FX rate source exists in the current data model.")

    return limitations

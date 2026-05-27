from __future__ import annotations

import json
from typing import Any

from app.services.metadata.contract_loader import (
    get_contract_columns,
    get_contract_source_name,
    load_all_source_contracts,
    load_source_contract,
)
from app.services.metadata.semantic_layer_loader import (
    load_clarification_rules,
    load_dimensions,
    load_metrics,
    load_time_semantics,
)
from app.services.metadata.semantic_metadata_loader import (
    get_relationships_for_sources,
    load_catalog,
    load_data_product_contracts,
    load_relationships,
)


def build_metadata_context() -> dict[str, Any]:
    """Build metadata catalog for LLM planning and deterministic validation."""
    source_contracts = load_all_source_contracts()
    metrics = load_metrics()
    dimensions = load_dimensions()
    time_semantics = load_time_semantics()
    clarification_rules = load_clarification_rules()
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
            "optional_sources": data_product.get("optional_sources", []),
            "primary_source": data_product.get("primary_source"),
            "relationships": data_product.get("relationships", []),
            "grain": data_product.get("grain", []),
            "metrics": data_product.get("metrics", []),
            "dimensions": data_product.get("dimensions", []),
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
        "clarification_rules": clarification_rules,
        "known_limitations": known_limitations,
        "allowed_sources": sorted(sources.keys()),
        "allowed_metrics": sorted(metrics.keys()),
        "allowed_dimensions": sorted(dimensions.keys()),
        "allowed_data_products": sorted(data_product_context.keys()),
    }


def build_llm_metadata_prompt_context(metadata_context: dict[str, Any], *, selected_sources: list[str] | None = None) -> str:
    """Render compact metadata context for SQL/artifact generation prompts.

    This function is still richer than the Step 2 request-planner context because
    downstream generation needs source columns, relationships, and data-product
    structure. For request classification, use build_request_planner_prompt_context.
    """
    selected_sources = [source for source in selected_sources or [] if source in metadata_context.get("sources", {})]

    source_names = selected_sources or list(metadata_context.get("sources", {}).keys())
    sources = {
        source_name: _compact_source_for_prompt(metadata_context["sources"][source_name])
        for source_name in source_names
        if source_name in metadata_context.get("sources", {})
    }

    relationships = get_relationships_for_sources(selected_sources) if selected_sources else metadata_context.get("relationships", [])
    relationships = [_compact_relationship_for_prompt(item) for item in relationships if isinstance(item, dict)]

    data_products = {
        name: _compact_data_product_for_prompt(product)
        for name, product in metadata_context.get("data_products", {}).items()
        if isinstance(product, dict)
    }

    metrics = {
        name: _compact_metric_for_prompt(metric)
        for name, metric in metadata_context.get("metrics", {}).items()
        if isinstance(metric, dict)
    }

    dimensions = {
        name: _compact_dimension_for_prompt(dimension)
        for name, dimension in metadata_context.get("dimensions", {}).items()
        if isinstance(dimension, dict)
    }

    prompt_context = {
        "sources": sources,
        "metrics": metrics,
        "dimensions": dimensions,
        "relationships": relationships,
        "data_products": data_products,
        "known_limitations": metadata_context.get("known_limitations", []),
        "allowed_sources": metadata_context.get("allowed_sources", []),
        "allowed_metrics": metadata_context.get("allowed_metrics", []),
        "allowed_dimensions": metadata_context.get("allowed_dimensions", []),
        "allowed_data_products": metadata_context.get("allowed_data_products", []),
    }

    return json.dumps(prompt_context, ensure_ascii=False, indent=2, default=str)


def build_request_planner_prompt_context(metadata_context: dict[str, Any]) -> str:
    """Render a small context for Step 2 request classification.

    Step 2 only decides route/source/metric/clarification. It should not receive
    artifact-plan examples or long column descriptions because that increases
    incomplete/invalid JSON risk.
    """
    sources = {
        name: _planner_source_for_prompt(source)
        for name, source in metadata_context.get("sources", {}).items()
        if isinstance(source, dict)
    }

    metrics = {
        name: _planner_metric_for_prompt(metric)
        for name, metric in metadata_context.get("metrics", {}).items()
        if isinstance(metric, dict)
    }

    dimensions = {
        name: _planner_dimension_for_prompt(dimension)
        for name, dimension in metadata_context.get("dimensions", {}).items()
        if isinstance(dimension, dict)
    }

    data_products = {
        name: _planner_data_product_for_prompt(product)
        for name, product in metadata_context.get("data_products", {}).items()
        if isinstance(product, dict)
    }

    clarification_rules = [
        _planner_clarification_rule_for_prompt(rule)
        for rule in metadata_context.get("clarification_rules", [])
        if isinstance(rule, dict) and rule.get("enabled", True)
    ]

    prompt_context = {
        "allowed_sources": metadata_context.get("allowed_sources", []),
        "allowed_metrics": metadata_context.get("allowed_metrics", []),
        "allowed_dimensions": metadata_context.get("allowed_dimensions", []),
        "allowed_data_products": metadata_context.get("allowed_data_products", []),
        "sources": sources,
        "metrics": metrics,
        "dimensions": dimensions,
        "data_products": data_products,
        "clarification_rules": clarification_rules,
        "known_limitations": metadata_context.get("known_limitations", []),
    }

    return json.dumps(prompt_context, ensure_ascii=False, indent=2, default=str)


def _compact_source_for_prompt(source: dict[str, Any]) -> dict[str, Any]:
    columns = source.get("columns", {}) or {}
    return {
        "name": source.get("name"),
        "description": source.get("description"),
        "aliases": source.get("aliases", [])[:6],
        "dbt_source": source.get("dbt_source"),
        "grain": (source.get("business_context") or {}).get("grain", []),
        "columns": {
            column_name: {
                "type": column.get("type"),
                "description": column.get("description"),
                "primary_key": column.get("primary_key", False),
                "valid_values": column.get("accepted_values") or column.get("valid_values"),
            }
            for column_name, column in columns.items()
        },
        "business_notes": (source.get("business_context") or {}).get("notes", [])[:3],
    }


def _compact_metric_for_prompt(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": metric.get("label"),
        "description": metric.get("description"),
        "business_terms": metric.get("business_terms", [])[:8],
        "generic_terms": metric.get("generic_terms", [])[:6],
        "ambiguity_group": metric.get("ambiguity_group"),
        "base_source": metric.get("base_source"),
        "value_expression": metric.get("value_expression"),
        "date_column": metric.get("date_column"),
        "default_filters": metric.get("default_filters", []),
    }


def _compact_dimension_for_prompt(dimension: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": dimension.get("label"),
        "business_terms": dimension.get("business_terms", [])[:6],
        "source": dimension.get("source"),
        "key": dimension.get("key"),
        "column": dimension.get("column"),
        "label_column": dimension.get("label_column"),
    }


def _compact_relationship_for_prompt(relationship: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": relationship.get("id"),
        "left_source": relationship.get("left_source"),
        "right_source": relationship.get("right_source"),
        "left_key": relationship.get("left_key"),
        "right_key": relationship.get("right_key"),
        "relationship_type": relationship.get("relationship_type"),
        "recommended_join_type": relationship.get("recommended_join_type"),
        "business_meaning": relationship.get("business_meaning"),
    }


def _compact_data_product_for_prompt(product: dict[str, Any]) -> dict[str, Any]:
    artifact_plan = product.get("artifact_plan_examples") or {}
    return {
        "name": product.get("name"),
        "package_name": product.get("package_name"),
        "description": product.get("description"),
        "aliases": product.get("aliases", [])[:8],
        "sources": product.get("sources", []),
        "optional_sources": product.get("optional_sources", []),
        "primary_source": product.get("primary_source"),
        "relationships": product.get("relationships", []),
        "grain": product.get("grain", []),
        "metrics": product.get("metrics", []),
        "known_business_questions": product.get("known_business_questions", [])[:2],
        "artifact_plan_example": {
            "final_mart_name": artifact_plan.get("final_mart_name"),
            "model_files": artifact_plan.get("model_files", []),
            "test_files": artifact_plan.get("test_files", []),
            "documentation_files": artifact_plan.get("documentation_files", []),
        },
    }


def _planner_source_for_prompt(source: dict[str, Any]) -> dict[str, Any]:
    columns = source.get("columns", {}) or {}
    return {
        "description": source.get("description"),
        "aliases": _as_string_list(source.get("aliases"))[:5],
        "columns": sorted(str(column_name) for column_name in columns.keys()),
    }


def _planner_metric_for_prompt(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": metric.get("label"),
        "description": metric.get("description"),
        "business_terms": _as_string_list(metric.get("business_terms"))[:6],
        "generic_terms": _as_string_list(metric.get("generic_terms"))[:4],
        "ambiguity_group": metric.get("ambiguity_group"),
        "base_source": metric.get("base_source"),
        "date_column": metric.get("date_column"),
        "default_dimensions": _as_string_list(metric.get("default_dimensions"))[:6],
    }


def _planner_dimension_for_prompt(dimension: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": dimension.get("label"),
        "business_terms": _as_string_list(dimension.get("business_terms"))[:5],
        "source": dimension.get("source"),
        "column": dimension.get("column") or dimension.get("label_column"),
    }


def _planner_data_product_for_prompt(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": product.get("description"),
        "aliases": _as_string_list(product.get("aliases"))[:6],
        "sources": _as_string_list(product.get("sources")),
        "optional_sources": _as_string_list(product.get("optional_sources")),
        "primary_source": product.get("primary_source"),
        "grain": _as_string_list(product.get("grain")),
        "metrics": _extract_data_product_metric_names(product.get("metrics")),
        "dimensions": _as_string_list(product.get("dimensions")),
    }


def _planner_clarification_rule_for_prompt(rule: dict[str, Any]) -> dict[str, Any]:
    clarification = rule.get("clarification") if isinstance(rule.get("clarification"), dict) else {}
    options = rule.get("options") if isinstance(rule.get("options"), list) else []
    return {
        "id": rule.get("id"),
        "description": rule.get("description"),
        "match": rule.get("match", {}),
        "question": clarification.get("question"),
        "issue_summary": clarification.get("issue_summary"),
        "recommended_option_id": clarification.get("recommended_option_id"),
        "option_ids": [str(option.get("id")) for option in options if isinstance(option, dict) and option.get("id")],
        "option_labels": [str(option.get("label")) for option in options if isinstance(option, dict) and option.get("label")],
    }


def _extract_data_product_metric_names(metrics: Any) -> list[str]:
    if not isinstance(metrics, list):
        return []

    names: list[str] = []
    for metric in metrics:
        if isinstance(metric, dict):
            name = str(metric.get("name", "")).strip()
        else:
            name = str(metric).strip()
        if name:
            names.append(name)
    return names


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
    return [
        "Do not invent tables or columns that are not present in the metadata context.",
        "Direct analytics SQL must be read-only SELECT/WITH SQL.",
        "Use only metrics, dimensions, data products, and clarification rules declared in metadata/config.",
    ]
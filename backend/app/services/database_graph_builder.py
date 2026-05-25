from __future__ import annotations

from typing import Any

from app.services.contract_loader import (
    get_contract_columns,
    get_contract_source_name,
    load_all_source_contracts,
)
from app.services.database_service import fetch_one, quote_identifier, table_exists
from app.services.semantic_layer_loader import load_dimensions, load_metrics
from app.services.semantic_metadata_loader import (
    load_catalog,
    load_data_product_contracts,
    load_relationships,
)


def build_database_graph() -> dict[str, Any]:
    """Build a deterministic database graph from PipeForge contracts.

    The graph is intentionally generated from YAML contracts + the live SQLite
    database metadata. It does not use an LLM and does not hard-code any business
    table names. The frontend can render this payload as an ERD/schema map.
    """

    warnings: list[str] = []

    catalog = _safe_load(load_catalog, fallback={}, warnings=warnings, label="catalog.yml")
    relationship_metadata = _safe_load(
        load_relationships,
        fallback={"relationships": []},
        warnings=warnings,
        label="relationships.yml",
    )
    source_contracts = _safe_load(
        load_all_source_contracts,
        fallback=[],
        warnings=warnings,
        label="source contracts",
    )
    metrics = _safe_load(load_metrics, fallback={}, warnings=warnings, label="metrics.yml")
    dimensions = _safe_load(load_dimensions, fallback={}, warnings=warnings, label="dimensions.yml")
    data_products = _safe_load(
        load_data_product_contracts,
        fallback=[],
        warnings=warnings,
        label="data product contracts",
    )

    catalog_sources = catalog.get("sources", [])
    if not isinstance(catalog_sources, list):
        catalog_sources = []
        warnings.append("catalog.yml did not contain a valid sources list.")

    contract_by_source = _index_contracts(source_contracts, warnings)
    metrics_by_source = _index_metrics_by_source(metrics)
    dimensions_by_source = _index_dimensions_by_source(dimensions)
    data_products_by_source = _index_data_products_by_source(data_products)

    nodes: list[dict[str, Any]] = []

    for source in catalog_sources:
        if not isinstance(source, dict):
            continue

        source_name = str(source.get("name", "")).strip()
        if not source_name:
            continue

        table_name = str(source.get("table_name") or source_name)
        contract = contract_by_source.get(source_name)
        columns = _build_columns(contract, source)

        if contract is None:
            warnings.append(f"Missing source contract for source={source_name}.")

        row_count = _get_row_count(table_name, warnings)

        nodes.append(
            {
                "id": source_name,
                "label": source_name,
                "tableName": table_name,
                "sourceRole": str(source.get("source_role") or "source"),
                "businessEntity": source.get("business_entity"),
                "grain": source.get("grain"),
                "primaryKey": source.get("primary_key") or _infer_primary_key(columns),
                "businessMeaning": source.get("business_meaning"),
                "importantColumns": _as_string_list(source.get("important_columns")),
                "keywords": _as_string_list(source.get("keywords")),
                "rowCount": row_count,
                "columns": columns,
                "metrics": metrics_by_source.get(source_name, []),
                "dimensions": dimensions_by_source.get(source_name, []),
                "dataProducts": data_products_by_source.get(source_name, []),
            }
        )

    relationships = relationship_metadata.get("relationships", [])
    if not isinstance(relationships, list):
        relationships = []
        warnings.append("relationships.yml did not contain a valid relationships list.")

    edges = [_build_edge(relationship) for relationship in relationships if isinstance(relationship, dict)]

    node_ids = {node["id"] for node in nodes}
    filtered_edges: list[dict[str, Any]] = []
    for edge in edges:
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            warnings.append(
                f"Relationship {edge['id']} references missing nodes: "
                f"{edge['from']} -> {edge['to']}."
            )
            continue
        filtered_edges.append(edge)

    groups = _build_groups(nodes)

    return {
        "database": {
            "name": catalog.get("database", {}).get("name") if isinstance(catalog.get("database"), dict) else None,
            "domain": catalog.get("database", {}).get("domain") if isinstance(catalog.get("database"), dict) else None,
            "description": catalog.get("database", {}).get("description")
            if isinstance(catalog.get("database"), dict)
            else None,
        },
        "summary": {
            "tableCount": len(nodes),
            "relationshipCount": len(filtered_edges),
            "metricCount": len(metrics),
            "dimensionCount": len(dimensions),
            "dataProductCount": len(data_products),
        },
        "nodes": nodes,
        "edges": filtered_edges,
        "groups": groups,
        "warnings": warnings,
    }


def _safe_load(loader, fallback: Any, warnings: list[str], label: str) -> Any:
    try:
        return loader()
    except Exception as exc:
        warnings.append(f"Could not load {label}: {exc}")
        return fallback


def _index_contracts(
    contracts: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}

    for contract in contracts:
        try:
            source_name = get_contract_source_name(contract)
        except Exception as exc:
            warnings.append(f"Could not read source contract name: {exc}")
            continue
        indexed[source_name] = contract

    return indexed


def _index_metrics_by_source(metrics: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}

    for metric_id, metric in metrics.items():
        source = metric.get("base_source")
        if not isinstance(source, str) or not source.strip():
            continue

        indexed.setdefault(source, []).append(
            {
                "id": metric_id,
                "label": metric.get("label") or metric_id,
                "description": metric.get("description"),
                "aggregateExpression": metric.get("aggregate_expression"),
                "dateColumn": metric.get("date_column"),
                "currencyColumn": metric.get("currency_column"),
            }
        )

    return indexed


def _index_dimensions_by_source(
    dimensions: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}

    for dimension_id, dimension in dimensions.items():
        source = dimension.get("source")
        if not isinstance(source, str) or source in {"metric_base", ""}:
            continue

        indexed.setdefault(source, []).append(
            {
                "id": dimension_id,
                "label": dimension.get("label") or dimension_id,
                "column": dimension.get("column"),
                "labelColumn": dimension.get("label_column"),
                "key": dimension.get("key"),
            }
        )

    return indexed


def _index_data_products_by_source(
    data_products: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    indexed: dict[str, list[dict[str, Any]]] = {}

    for contract in data_products:
        data_product = contract.get("data_product", {})
        if not isinstance(data_product, dict):
            continue

        product_id = str(data_product.get("name", "")).strip()
        if not product_id:
            continue

        product_payload = {
            "id": product_id,
            "label": data_product.get("package_name") or product_id,
            "description": data_product.get("description"),
        }

        for source in _as_string_list(data_product.get("sources")):
            indexed.setdefault(source, []).append(product_payload)

    return indexed


def _build_columns(
    contract: dict[str, Any] | None,
    catalog_source: dict[str, Any],
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    primary_key = str(catalog_source.get("primary_key") or "")

    if contract is not None:
        contract_columns = get_contract_columns(contract)

        for column_name, column in contract_columns.items():
            relationship_hint = column.get("relationship_hints")
            reference = None

            if isinstance(relationship_hint, dict):
                raw_reference = relationship_hint.get("references")
                if isinstance(raw_reference, dict):
                    reference = {
                        "source": raw_reference.get("source"),
                        "column": raw_reference.get("column"),
                    }

            columns.append(
                {
                    "name": column_name,
                    "type": column.get("type"),
                    "description": column.get("description"),
                    "isPrimaryKey": bool(column.get("primary_key")) or column_name == primary_key,
                    "nullable": bool(column.get("nullable")),
                    "validValues": column.get("valid_values", []),
                    "reference": reference,
                }
            )

    if columns:
        return columns

    for column_name in _as_string_list(catalog_source.get("important_columns")):
        columns.append(
            {
                "name": column_name,
                "type": None,
                "description": None,
                "isPrimaryKey": column_name == primary_key,
                "nullable": None,
                "validValues": [],
                "reference": None,
            }
        )

    return columns


def _build_edge(relationship: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(relationship.get("id")),
        "from": relationship.get("left_source"),
        "to": relationship.get("right_source"),
        "fromColumn": relationship.get("left_key"),
        "toColumn": relationship.get("right_key"),
        "relationshipType": relationship.get("relationship_type"),
        "recommendedJoinType": relationship.get("recommended_join_type"),
        "businessMeaning": relationship.get("business_meaning"),
        "requiredFor": _as_string_list(relationship.get("required_for")),
        "warnings": _as_string_list(relationship.get("warnings")),
        "validation": relationship.get("validation") if isinstance(relationship.get("validation"), dict) else {},
    }


def _build_groups(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}

    for node in nodes:
        role = str(node.get("sourceRole") or "source")
        grouped.setdefault(role, []).append(node["id"])

    label_by_role = {
        "dimension": "Dimensions",
        "fact": "Facts",
        "source": "Sources",
    }

    return [
        {
            "id": role,
            "label": label_by_role.get(role, role.replace("_", " ").title()),
            "nodeIds": node_ids,
        }
        for role, node_ids in sorted(grouped.items())
    ]


def _get_row_count(table_name: str, warnings: list[str]) -> int | None:
    try:
        if not table_exists(table_name):
            warnings.append(f"SQLite table not found for table_name={table_name}.")
            return None

        quoted = quote_identifier(table_name)
        row = fetch_one(f"SELECT COUNT(*) AS row_count FROM {quoted}")

        if not row:
            return None

        return int(row["row_count"])
    except Exception as exc:
        warnings.append(f"Could not read row count for table_name={table_name}: {exc}")
        return None


def _infer_primary_key(columns: list[dict[str, Any]]) -> str | None:
    for column in columns:
        if column.get("isPrimaryKey"):
            return str(column.get("name"))

    return None


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]

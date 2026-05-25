from __future__ import annotations

import re
from typing import Any, TypedDict

from app.services.semantic_metadata_loader import (
    get_data_product_artifact_plan,
    load_data_product_contracts,
)


class DataProductSelection(TypedDict):
    data_product_name: str
    contract: dict[str, Any]
    data_product: dict[str, Any]
    artifact_plan: dict[str, Any]
    sources: list[str]
    relationships: list[str]
    score: int
    reason: str
    available_data_products: list[str]


def select_data_product_for_prompt(prompt: str) -> DataProductSelection:
    contracts = load_data_product_contracts()

    if not contracts:
        raise RuntimeError(
            "No data product contracts found in backend/app/contracts/data_products."
        )

    scored = [_score_data_product(prompt, contract) for contract in contracts]
    scored.sort(key=lambda item: item["score"], reverse=True)

    best = scored[0]

    if best["score"] <= 0:
        available = [_data_product_name(contract) for contract in contracts]
        raise RuntimeError(
            "The request looks multi-source, but no data product contract matched it. "
            f"Available data products: {', '.join(available)}"
        )

    contract = best["contract"]
    data_product = contract["data_product"]
    artifact_plan = get_data_product_artifact_plan(contract)

    return {
        "data_product_name": data_product["name"],
        "contract": contract,
        "data_product": data_product,
        "artifact_plan": artifact_plan,
        "sources": [str(source) for source in data_product.get("sources", [])],
        "relationships": [str(relationship) for relationship in data_product.get("relationships", [])],
        "score": best["score"],
        "reason": best["reason"],
        "available_data_products": [_data_product_name(item) for item in contracts],
    }


def _score_data_product(prompt: str, contract: dict[str, Any]) -> dict[str, Any]:
    data_product = contract["data_product"]
    lowered_prompt = prompt.lower()
    prompt_tokens = _tokens(prompt)

    score = 0
    matched: list[str] = []

    name = str(data_product.get("name", ""))
    package_name = str(data_product.get("package_name", ""))
    description = str(data_product.get("description", ""))

    for exact_value, weight in [
        (name.replace("_", " "), 18),
        (name, 18),
        (package_name, 14),
    ]:
        if exact_value and exact_value.lower() in lowered_prompt:
            score += weight
            matched.append(exact_value)

    aliases = [
        str(alias)
        for alias in data_product.get("aliases", [])
        if str(alias).strip()
    ]

    for alias in aliases:
        alias_lower = alias.lower()
        alias_tokens = _tokens(alias)

        if alias_lower and alias_lower in lowered_prompt:
            score += 20 + len(alias_tokens)
            matched.append(alias)
            continue

        overlap = prompt_tokens.intersection(alias_tokens)
        if overlap and len(overlap) >= min(2, len(alias_tokens)):
            score += 3 * len(overlap)
            matched.append(alias)

    source_names = [str(source) for source in data_product.get("sources", [])]
    for source_name in source_names:
        source_label = source_name.replace("_", " ")
        if source_name.lower() in lowered_prompt or source_label.lower() in lowered_prompt:
            score += 4
            matched.append(source_name)

    relationship_names = [str(item) for item in data_product.get("relationships", [])]
    for relationship_name in relationship_names:
        for token in relationship_name.replace("_", " ").split():
            if token and token in prompt_tokens:
                score += 1

    metric_items: list[str] = []
    for metric in data_product.get("metrics", []):
        if isinstance(metric, dict):
            metric_items.append(str(metric.get("name", "")))
            metric_items.append(str(metric.get("description", "")))

    for metric_item in metric_items:
        metric_tokens = _tokens(metric_item)
        overlap = prompt_tokens.intersection(metric_tokens)
        if overlap:
            score += len(overlap)
            matched.append(metric_item)

    description_overlap = prompt_tokens.intersection(_tokens(description))
    if description_overlap:
        score += len(description_overlap)

    # Tie-breaker nudges for common product intents.
    if {"revenue", "360"}.issubset(prompt_tokens) and name == "subscription_revenue_360":
        score += 25
        matched.append("revenue 360 intent")
    if {"collection", "health"}.issubset(prompt_tokens) and name == "subscription_collection_health":
        score += 25
        matched.append("collection health intent")
    if {"reconcile", "invoices", "payments"}.intersection(prompt_tokens) and name == "stripe_billing_reconciliation":
        if "revenue 360" not in lowered_prompt and "collection health" not in lowered_prompt:
            score += 10
            matched.append("invoice payment reconciliation intent")

    reason = (
        "Matched data product metadata: " + "; ".join(_dedupe_keep_order(matched)[:8])
        if matched
        else "No data product metadata matched the prompt."
    )

    return {
        "contract": contract,
        "score": score,
        "reason": reason,
    }


def _data_product_name(contract: dict[str, Any]) -> str:
    data_product = contract.get("data_product", {})
    return str(data_product.get("name", "unknown_data_product"))


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9_]+", " ", text.lower())
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "we",
        "need",
        "want",
        "build",
        "create",
        "report",
    }
    return {
        token
        for token in normalized.split()
        if token and token not in stopwords and len(token) > 1
    }


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for item in items:
        normalized = item.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(item)

    return result

from __future__ import annotations

import re
from typing import Literal, TypedDict

from app.services.metadata.contract_loader import get_contract_aliases, load_all_source_contracts
from app.services.metadata.semantic_layer_loader import load_dimensions, load_metrics, load_time_semantics
from app.services.metadata.semantic_metadata_loader import load_catalog, load_data_product_contracts


DomainRelevance = Literal[
    "relevant_to_database",
    "ambiguous_database_request",
    "out_of_scope",
]


class DomainRelevanceClassification(TypedDict):
    relevance: DomainRelevance
    is_relevant_to_database: bool
    should_ask_clarification: bool
    needs_llm_fallback: bool
    confidence: float
    matched_terms: list[str]
    weak_matched_terms: list[str]
    reason: str
    message: str


_WEAK_DATABASE_TERMS = [
    "data",
    "database",
    "table",
    "tables",
    "column",
    "columns",
    "row",
    "rows",
    "record",
    "records",
    "metric",
    "metrics",
    "number",
    "numbers",
    "analysis",
    "analytics",
    "report",
    "dashboard",
    "chart",
    "graph",
    "kpi",
    "sql",
    "dbt",
]

# Hard-code note:
# This list is intentionally narrow. It is only used to reject clearly unrelated
# prompts without spending an LLM call. Any uncertain prompt should go to the LLM
# fallback instead of being rejected by this list.
_OBVIOUS_OUT_OF_SCOPE_PATTERNS = [
    r"\bweather\b",
    r"\btemperature\b",
    r"\bforecast\b",
    r"\bpoem\b",
    r"\bjoke\b",
    r"\bstory\b",
    r"\bpresident\b",
    r"\bprime minister\b",
    r"\bfootball\b",
    r"\bsoccer\b",
    r"\bmovie\b",
    r"\brecipe\b",
    r"\btranslate\b",
    r"\binstall docker\b",
]

_OUT_OF_SCOPE_EXAMPLE_MESSAGE = """This request does not appear to be related to the available PipeForge database or data product workflow.

I can help with questions about customers, plans, subscriptions, invoices, payments, billed revenue, collected revenue, MRR, outstanding invoice amount, collection rate, or generated dbt-style artifacts.

Please rephrase your request as a database, analytics, or data product question."""

_AMBIGUOUS_DATABASE_MESSAGE = """This request might be related to analytics or data work, but it is too broad for me to route safely.

Please specify one of the available business areas or metrics, for example:
- billed revenue
- collected revenue
- MRR
- outstanding invoice amount
- collection rate
- customers
- plans
- subscriptions
- invoices
- payments

Example: "Which customer generated the highest billed revenue last month?"
"""


def classify_domain_relevance(prompt: str) -> DomainRelevanceClassification:
    normalized = _normalize(prompt)

    strong_terms = _load_strong_database_terms()
    matched_strong_terms = _find_terms(normalized, strong_terms)
    matched_weak_terms = _find_terms(normalized, _WEAK_DATABASE_TERMS)

    if matched_strong_terms:
        confidence = _score_strong_match_confidence(matched_strong_terms, normalized)
        return {
            "relevance": "relevant_to_database",
            "is_relevant_to_database": True,
            "should_ask_clarification": False,
            "needs_llm_fallback": False,
            "confidence": confidence,
            "matched_terms": matched_strong_terms,
            "weak_matched_terms": matched_weak_terms,
            "reason": "The prompt matches known database, metric, dimension, source, or data product terms.",
            "message": "",
        }

    if _looks_obviously_out_of_scope(normalized) and not matched_weak_terms:
        return {
            "relevance": "out_of_scope",
            "is_relevant_to_database": False,
            "should_ask_clarification": False,
            "needs_llm_fallback": False,
            "confidence": 0.95,
            "matched_terms": [],
            "weak_matched_terms": [],
            "reason": "The prompt matches a narrow obvious out-of-scope pattern and no database terms.",
            "message": _OUT_OF_SCOPE_EXAMPLE_MESSAGE,
        }

    if matched_weak_terms:
        return {
            "relevance": "ambiguous_database_request",
            "is_relevant_to_database": False,
            "should_ask_clarification": True,
            "needs_llm_fallback": True,
            "confidence": 0.45,
            "matched_terms": [],
            "weak_matched_terms": matched_weak_terms,
            "reason": (
                "The prompt contains generic data/analytics words, but does not match a known "
                "metric, dimension, source, relationship, or data product. LLM fallback is recommended."
            ),
            "message": _AMBIGUOUS_DATABASE_MESSAGE,
        }

    return {
        "relevance": "ambiguous_database_request",
        "is_relevant_to_database": False,
        "should_ask_clarification": True,
        "needs_llm_fallback": True,
        "confidence": 0.30,
        "matched_terms": [],
        "weak_matched_terms": [],
        "reason": (
            "The prompt does not match known PipeForge metadata. It is not obviously out-of-scope, "
            "so LLM fallback should classify it before routing."
        ),
        "message": _AMBIGUOUS_DATABASE_MESSAGE,
    }


def _load_strong_database_terms() -> list[str]:
    terms: set[str] = set()

    terms.update(_load_metric_terms())
    terms.update(_load_dimension_terms())
    terms.update(_load_time_terms())
    terms.update(_load_catalog_terms())
    terms.update(_load_source_contract_terms())
    terms.update(_load_data_product_terms())

    return sorted(
        {
            term.strip().lower()
            for term in terms
            if isinstance(term, str) and term.strip() and len(term.strip()) >= 2
        },
        key=len,
        reverse=True,
    )


def _load_metric_terms() -> set[str]:
    terms: set[str] = set()

    try:
        metrics = load_metrics()
    except Exception:
        return terms

    for metric_name, metric in metrics.items():
        terms.add(metric_name)
        terms.add(metric_name.replace("_", " "))

        for key in ["label", "description", "base_source", "value_expression", "aggregate_expression"]:
            value = metric.get(key)
            if isinstance(value, str):
                terms.add(value)
                terms.add(value.replace("_", " "))

        for key in ["business_terms", "generic_terms", "default_dimensions", "assumptions"]:
            value = metric.get(key)
            if isinstance(value, list):
                terms.update(str(item) for item in value)
                terms.update(str(item).replace("_", " ") for item in value)

    return terms


def _load_dimension_terms() -> set[str]:
    terms: set[str] = set()

    try:
        dimensions = load_dimensions()
    except Exception:
        return terms

    for dimension_name, dimension in dimensions.items():
        terms.add(dimension_name)
        terms.add(dimension_name.replace("_", " "))

        for key in ["label", "source", "key", "column", "label_column"]:
            value = dimension.get(key)
            if isinstance(value, str):
                terms.add(value)
                terms.add(value.replace("_", " "))

        for key in ["business_terms", "default_columns", "attributes"]:
            value = dimension.get(key)
            if isinstance(value, list):
                for item in value:
                    terms.add(str(item))
                    terms.add(str(item).replace("_", " "))

    return terms


def _load_time_terms() -> set[str]:
    terms: set[str] = set()

    try:
        time_semantics = load_time_semantics()
    except Exception:
        return terms

    phrases = time_semantics.get("time_phrases", {})
    if not isinstance(phrases, dict):
        return terms

    for phrase_name, phrase in phrases.items():
        terms.add(str(phrase_name))
        terms.add(str(phrase_name).replace("_", " "))
        if not isinstance(phrase, dict):
            continue
        for term in phrase.get("business_terms", []):
            terms.add(str(term))
            terms.add(str(term).replace("_", " "))

    return terms


def _load_catalog_terms() -> set[str]:
    terms: set[str] = set()

    try:
        catalog = load_catalog()
    except Exception:
        return terms

    database = catalog.get("database", {})
    if isinstance(database, dict):
        for key in ["name", "domain", "description"]:
            value = database.get(key)
            if isinstance(value, str):
                terms.add(value)
                terms.add(value.replace("_", " "))

    sources = catalog.get("sources", [])
    if not isinstance(sources, list):
        return terms

    for source in sources:
        if not isinstance(source, dict):
            continue

        for key in [
            "name",
            "table_name",
            "business_entity",
            "grain",
            "primary_key",
            "business_meaning",
        ]:
            value = source.get(key)
            if isinstance(value, str):
                terms.add(value)
                terms.add(value.replace("_", " "))

        for key in ["important_columns", "keywords"]:
            value = source.get(key)
            if isinstance(value, list):
                for item in value:
                    terms.add(str(item))
                    terms.add(str(item).replace("_", " "))

    return terms


def _load_source_contract_terms() -> set[str]:
    terms: set[str] = set()

    try:
        contracts = load_all_source_contracts()
    except Exception:
        return terms

    for contract in contracts:
        source = contract.get("source", {})
        business_context = contract.get("business_context", {})
        columns = contract.get("columns", {})

        if isinstance(source, dict):
            source_name = str(source.get("name", ""))
            if source_name:
                terms.add(source_name)
                terms.add(source_name.replace("_", " "))

            terms.update(get_contract_aliases(contract))

        if isinstance(business_context, dict):
            for key in ["data_product_goal", "final_mart", "metric_name"]:
                value = business_context.get(key)
                if isinstance(value, str):
                    terms.add(value)
                    terms.add(value.replace("_", " "))

            for key in ["grain", "primary_metric_dimensions", "keywords"]:
                value = business_context.get(key)
                if isinstance(value, list):
                    for item in value:
                        terms.add(str(item))
                        terms.add(str(item).replace("_", " "))

        if isinstance(columns, dict):
            for column_name in columns.keys():
                terms.add(str(column_name))
                terms.add(str(column_name).replace("_", " "))

    return terms


def _load_data_product_terms() -> set[str]:
    terms: set[str] = set()

    try:
        contracts = load_data_product_contracts()
    except Exception:
        return terms

    for contract in contracts:
        data_product = contract.get("data_product", {})
        if not isinstance(data_product, dict):
            continue

        for key in ["name", "package_name", "description", "primary_source"]:
            value = data_product.get(key)
            if isinstance(value, str):
                terms.add(value)
                terms.add(value.replace("_", " "))

        for key in ["aliases", "sources", "relationships", "grain"]:
            value = data_product.get(key)
            if isinstance(value, list):
                for item in value:
                    terms.add(str(item))
                    terms.add(str(item).replace("_", " "))

        for metric in data_product.get("metrics", []):
            if isinstance(metric, dict):
                for key in ["name", "source", "description", "expression"]:
                    value = metric.get(key)
                    if isinstance(value, str):
                        terms.add(value)
                        terms.add(value.replace("_", " "))

    return terms


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _find_terms(text: str, terms: list[str]) -> list[str]:
    matched: list[str] = []

    for term in terms:
        normalized_term = _normalize(term)

        if not normalized_term:
            continue

        if len(normalized_term) <= 3:
            pattern = rf"\b{re.escape(normalized_term)}\b"
            found = re.search(pattern, text) is not None
        else:
            found = normalized_term in text

        if found:
            matched.append(normalized_term)

    deduped: list[str] = []
    seen: set[str] = set()

    for term in matched:
        if term not in seen:
            deduped.append(term)
            seen.add(term)

    return deduped[:20]


def _score_strong_match_confidence(matched_terms: list[str], text: str) -> float:
    if not matched_terms:
        return 0.0

    long_match_count = sum(1 for term in matched_terms if len(term) >= 8)
    exact_business_phrase_count = sum(1 for term in matched_terms if " " in term and len(term) >= 8)

    confidence = 0.70
    confidence += min(0.12, 0.03 * len(matched_terms))
    confidence += min(0.10, 0.03 * long_match_count)
    confidence += min(0.08, 0.04 * exact_business_phrase_count)

    if len(text.split()) <= 3 and len(matched_terms) == 1:
        confidence -= 0.12

    return round(max(0.50, min(confidence, 0.95)), 2)


def _looks_obviously_out_of_scope(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _OBVIOUS_OUT_OF_SCOPE_PATTERNS)
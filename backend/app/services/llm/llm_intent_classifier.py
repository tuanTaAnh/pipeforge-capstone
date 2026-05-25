from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from app.core.config import settings
from app.services.llm.llm_client import llm_client
from app.services.metadata.semantic_layer_loader import load_dimensions, load_metrics
from app.services.metadata.semantic_metadata_loader import load_catalog, load_data_product_contracts
from app.utils.prompt_loader import render_prompt


Relevance = Literal["relevant_to_database", "ambiguous_database_request", "out_of_scope"]
Intent = Literal[
    "direct_analytics_question",
    "data_product_generation",
    "clarification_needed",
    "non_database",
]


class LLMIntentClassification(TypedDict):
    relevance: Relevance
    intent: Intent
    confidence: float
    reason: str
    mapped_terms: dict[str, str]
    needs_clarification: bool
    clarifying_question: str | None
    suggested_options: list[str]
    used_llm: bool
    error: str | None


_ALLOWED_RELEVANCE = {
    "relevant_to_database",
    "ambiguous_database_request",
    "out_of_scope",
}

_ALLOWED_INTENTS = {
    "direct_analytics_question",
    "data_product_generation",
    "clarification_needed",
    "non_database",
}


async def classify_intent_with_llm(
    prompt: str,
    domain_classification: dict[str, Any],
) -> LLMIntentClassification:
    if not settings.use_llm_intent_classifier:
        return _fallback_classification(
            reason="LLM intent classifier is disabled by configuration.",
            error=None,
        )

    try:
        system_prompt = (
            "You are a strict JSON-only classifier for PipeForge. "
            "You classify whether a user prompt is related to the available database, "
            "whether it is a direct analytics question, data product generation task, "
            "ambiguous data request, or out-of-scope request. Return only valid JSON."
        )

        user_prompt = render_prompt(
            "intent_classifier_prompt.txt",
            METRICS_CONTEXT=_compact_metrics_context(),
            DIMENSIONS_CONTEXT=_compact_dimensions_context(),
            CATALOG_CONTEXT=_compact_catalog_context(),
            DATA_PRODUCT_CONTEXT=_compact_data_product_context(),
            DOMAIN_CLASSIFICATION_CONTEXT=json.dumps(
                domain_classification,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            USER_PROMPT=prompt,
        )

        raw_result = await llm_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=900,
        )

        return _normalize_llm_result(raw_result)
    except Exception as exc:
        return _fallback_classification(
            reason="LLM intent classifier failed; falling back to safe clarification.",
            error=str(exc),
        )


def merge_domain_and_llm_classification(
    domain_classification: dict[str, Any],
    llm_classification: LLMIntentClassification | None,
) -> dict[str, Any]:
    if not llm_classification:
        return {
            "source": "deterministic",
            "relevance": domain_classification.get("relevance", "ambiguous_database_request"),
            "intent": "clarification_needed",
            "confidence": float(domain_classification.get("confidence", 0.0)),
            "reason": domain_classification.get("reason", "No LLM classification was provided."),
            "needs_clarification": bool(domain_classification.get("should_ask_clarification", True)),
            "clarifying_question": domain_classification.get("message"),
            "suggested_options": [],
            "mapped_terms": {},
        }

    high_threshold = settings.llm_intent_classifier_confidence_threshold
    low_threshold = settings.llm_intent_classifier_low_confidence_threshold
    confidence = float(llm_classification.get("confidence", 0.0))

    if confidence >= high_threshold:
        return {
            "source": "llm",
            **llm_classification,
        }

    if confidence >= low_threshold:
        return {
            "source": "llm_low_confidence",
            "relevance": "ambiguous_database_request",
            "intent": "clarification_needed",
            "confidence": confidence,
            "reason": (
                "LLM classification confidence was below the routing threshold. "
                f"LLM reason: {llm_classification.get('reason', '')}"
            ),
            "mapped_terms": llm_classification.get("mapped_terms", {}),
            "needs_clarification": True,
            "clarifying_question": llm_classification.get("clarifying_question")
            or _default_clarifying_question(),
            "suggested_options": llm_classification.get("suggested_options", []),
            "used_llm": True,
            "error": llm_classification.get("error"),
        }

    return {
        "source": "llm_very_low_confidence",
        "relevance": "ambiguous_database_request",
        "intent": "clarification_needed",
        "confidence": confidence,
        "reason": (
            "LLM classification confidence was too low for safe routing. "
            f"LLM reason: {llm_classification.get('reason', '')}"
        ),
        "mapped_terms": llm_classification.get("mapped_terms", {}),
        "needs_clarification": True,
        "clarifying_question": _default_clarifying_question(),
        "suggested_options": _default_suggested_options(),
        "used_llm": True,
        "error": llm_classification.get("error"),
    }


def _normalize_llm_result(raw: dict[str, Any]) -> LLMIntentClassification:
    relevance = str(raw.get("relevance", "ambiguous_database_request"))
    intent = str(raw.get("intent", "clarification_needed"))

    if relevance not in _ALLOWED_RELEVANCE:
        relevance = "ambiguous_database_request"

    if intent not in _ALLOWED_INTENTS:
        intent = "clarification_needed"

    confidence = _safe_float(raw.get("confidence", 0.0))
    confidence = max(0.0, min(confidence, 1.0))

    mapped_terms = raw.get("mapped_terms", {})
    if not isinstance(mapped_terms, dict):
        mapped_terms = {}

    normalized_mapped_terms = {
        str(key): str(value)
        for key, value in mapped_terms.items()
        if str(key).strip() and str(value).strip()
    }

    suggested_options = raw.get("suggested_options", [])
    if not isinstance(suggested_options, list):
        suggested_options = []

    needs_clarification = bool(raw.get("needs_clarification", False))
    if relevance == "ambiguous_database_request" or intent == "clarification_needed":
        needs_clarification = True

    if relevance == "out_of_scope":
        intent = "non_database"
        needs_clarification = False

    clarifying_question = raw.get("clarifying_question")
    if clarifying_question is not None:
        clarifying_question = str(clarifying_question)

    return {
        "relevance": relevance,  # type: ignore[typeddict-item]
        "intent": intent,  # type: ignore[typeddict-item]
        "confidence": confidence,
        "reason": str(raw.get("reason", "")),
        "mapped_terms": normalized_mapped_terms,
        "needs_clarification": needs_clarification,
        "clarifying_question": clarifying_question,
        "suggested_options": [str(option) for option in suggested_options if str(option).strip()],
        "used_llm": True,
        "error": None,
    }


def _fallback_classification(reason: str, error: str | None) -> LLMIntentClassification:
    return {
        "relevance": "ambiguous_database_request",
        "intent": "clarification_needed",
        "confidence": 0.0,
        "reason": reason,
        "mapped_terms": {},
        "needs_clarification": True,
        "clarifying_question": _default_clarifying_question(),
        "suggested_options": _default_suggested_options(),
        "used_llm": False,
        "error": error,
    }


def _compact_metrics_context() -> str:
    metrics = load_metrics()
    compact: dict[str, Any] = {}

    for metric_name, metric in metrics.items():
        compact[metric_name] = {
            "label": metric.get("label"),
            "description": metric.get("description"),
            "business_terms": metric.get("business_terms", []),
            "generic_terms": metric.get("generic_terms", []),
            "ambiguity_group": metric.get("ambiguity_group"),
            "base_source": metric.get("base_source"),
            "aggregate_expression": metric.get("aggregate_expression"),
            "date_column": metric.get("date_column"),
            "default_dimensions": metric.get("default_dimensions", []),
        }

    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def _compact_dimensions_context() -> str:
    dimensions = load_dimensions()
    compact: dict[str, Any] = {}

    for dimension_name, dimension in dimensions.items():
        compact[dimension_name] = {
            "label": dimension.get("label"),
            "business_terms": dimension.get("business_terms", []),
            "source": dimension.get("source"),
            "key": dimension.get("key"),
            "column": dimension.get("column"),
            "label_column": dimension.get("label_column"),
            "attributes": dimension.get("attributes", []),
        }

    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def _compact_catalog_context() -> str:
    catalog = load_catalog()
    sources = catalog.get("sources", [])
    compact_sources = []

    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            compact_sources.append(
                {
                    "name": source.get("name"),
                    "table_name": source.get("table_name"),
                    "business_entity": source.get("business_entity"),
                    "grain": source.get("grain"),
                    "primary_key": source.get("primary_key"),
                    "important_columns": source.get("important_columns", []),
                    "keywords": source.get("keywords", []),
                    "business_meaning": source.get("business_meaning"),
                }
            )

    return json.dumps(compact_sources, ensure_ascii=False, indent=2, default=str)


def _compact_data_product_context() -> str:
    contracts = load_data_product_contracts()
    compact = []

    for contract in contracts:
        data_product = contract.get("data_product", {})
        if not isinstance(data_product, dict):
            continue
        compact.append(
            {
                "name": data_product.get("name"),
                "package_name": data_product.get("package_name"),
                "description": data_product.get("description"),
                "aliases": data_product.get("aliases", []),
                "sources": data_product.get("sources", []),
                "relationships": data_product.get("relationships", []),
                "grain": data_product.get("grain", []),
                "metrics": [
                    {
                        "name": metric.get("name"),
                        "description": metric.get("description"),
                    }
                    for metric in data_product.get("metrics", [])
                    if isinstance(metric, dict)
                ],
            }
        )

    return json.dumps(compact, ensure_ascii=False, indent=2, default=str)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _default_clarifying_question() -> str:
    return (
        "I could not route this safely. Which business metric or workflow should I use: "
        "billed revenue, collected revenue, MRR, outstanding invoice amount, collection rate, "
        "billing reconciliation, revenue 360, or collection health?"
    )


def _default_suggested_options() -> list[str]:
    return [
        "Billed revenue",
        "Collected revenue",
        "MRR",
        "Outstanding invoice amount",
        "Collection rate",
        "Billing reconciliation",
        "Revenue 360",
        "Collection health",
    ]
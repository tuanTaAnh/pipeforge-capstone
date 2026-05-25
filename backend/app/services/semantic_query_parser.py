from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.semantic_layer_loader import load_dimensions, load_metrics, load_time_semantics


@dataclass
class SemanticQueryPlan:
    prompt: str
    intent: str
    metric_name: str | None
    dimension_name: str | None
    time_phrase: str
    limit: int
    clarification_required: bool = False
    clarification_question: dict[str, Any] | None = None
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "intent": self.intent,
            "metric_name": self.metric_name,
            "dimension_name": self.dimension_name,
            "time_phrase": self.time_phrase,
            "limit": self.limit,
            "clarification_required": self.clarification_required,
            "clarification_question": self.clarification_question,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
        }


def parse_semantic_query(prompt: str, forced_metric_name: str | None = None) -> SemanticQueryPlan:
    metrics = load_metrics()
    dimensions = load_dimensions()
    time_semantics = load_time_semantics()
    normalized = _normalize(prompt)

    intent = _resolve_intent(normalized)
    metric_name, metric_ambiguity = _resolve_metric(normalized, metrics, forced_metric_name)
    dimension_name = _resolve_dimension(normalized, dimensions, intent)
    time_phrase = _resolve_time_phrase(normalized, time_semantics)
    limit = _resolve_limit(normalized, intent)

    assumptions: list[str] = []
    warnings: list[str] = []

    if metric_name and metric_name in metrics:
        assumptions.extend(str(item) for item in metrics[metric_name].get("assumptions", []))

    if time_phrase == "last_month":
        assumptions.append(
            "Last month is calculated relative to the latest available date in the selected metric source, not the system date."
        )

    if metric_ambiguity:
        return SemanticQueryPlan(
            prompt=prompt,
            intent=intent,
            metric_name=None,
            dimension_name=dimension_name,
            time_phrase=time_phrase,
            limit=limit,
            clarification_required=True,
            clarification_question=_build_metric_clarification_question(metrics),
            assumptions=assumptions,
            warnings=["The term revenue is ambiguous across billed revenue, collected revenue, and MRR."],
        )

    if not metric_name:
        return SemanticQueryPlan(
            prompt=prompt,
            intent=intent,
            metric_name=None,
            dimension_name=dimension_name,
            time_phrase=time_phrase,
            limit=limit,
            clarification_required=True,
            clarification_question=_build_metric_clarification_question(metrics),
            assumptions=assumptions,
            warnings=["No supported metric could be resolved from the question."],
        )

    if intent in {"top_k", "group_by"} and not dimension_name:
        dimension_name = "customer"
        assumptions.append("No dimension was explicitly resolved; defaulting to customer.")

    return SemanticQueryPlan(
        prompt=prompt,
        intent=intent,
        metric_name=metric_name,
        dimension_name=dimension_name,
        time_phrase=time_phrase,
        limit=limit,
        clarification_required=False,
        assumptions=assumptions,
        warnings=warnings,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _resolve_intent(text: str) -> str:
    if re.search(r"\b(highest|top|largest|biggest|most)\b", text):
        return "top_k"
    if re.search(r"\bby\b|\bgrouped by\b|\bbroken down by\b", text):
        return "group_by"
    if re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", text):
        return "count"
    return "aggregate"


def _resolve_metric(
    text: str,
    metrics: dict[str, dict[str, Any]],
    forced_metric_name: str | None,
) -> tuple[str | None, bool]:
    if forced_metric_name:
        return forced_metric_name, False

    explicit_matches: list[tuple[int, str]] = []

    for metric_name, metric in metrics.items():
        for term in metric.get("business_terms", []):
            term_text = str(term).lower().strip()
            if term_text and term_text in text:
                explicit_matches.append((len(term_text), metric_name))

    if explicit_matches:
        explicit_matches.sort(reverse=True)
        return explicit_matches[0][1], False

    generic_revenue_requested = re.search(r"\brevenue\b", text) is not None
    if generic_revenue_requested:
        return None, True

    if re.search(r"\binvoices?\b", text):
        return "invoice_count", False

    return None, False


def _resolve_dimension(
    text: str,
    dimensions: dict[str, dict[str, Any]],
    intent: str,
) -> str | None:
    matches: list[tuple[int, str]] = []

    for dimension_name, dimension in dimensions.items():
        for term in dimension.get("business_terms", []):
            term_text = str(term).lower().strip()
            if term_text and re.search(rf"\b{re.escape(term_text)}\b", text):
                matches.append((len(term_text), dimension_name))

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    if intent == "top_k":
        return "customer"

    return None


def _resolve_time_phrase(text: str, time_semantics: dict[str, Any]) -> str:
    phrases = time_semantics.get("time_phrases", {})

    if isinstance(phrases, dict):
        for phrase_name, phrase in phrases.items():
            if not isinstance(phrase, dict):
                continue
            for term in phrase.get("business_terms", []):
                term_text = str(term).lower().strip()
                if term_text and term_text in text:
                    return str(phrase_name)

    defaults = time_semantics.get("defaults", {})
    if isinstance(defaults, dict):
        return str(defaults.get("default_time_phrase", "last_month"))

    return "last_month"


def _resolve_limit(text: str, intent: str) -> int:
    top_match = re.search(r"\btop\s+(\d+)\b", text)
    if top_match:
        return max(1, min(int(top_match.group(1)), 100))

    return 1 if intent == "top_k" else 100


def _build_metric_clarification_question(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    option_metric_names = ["billed_revenue", "collected_revenue", "mrr"]
    options = []

    for metric_name in option_metric_names:
        metric = metrics.get(metric_name, {})
        label = str(metric.get("label") or metric_name)
        description = str(metric.get("description") or label)
        options.append(
            {
                "id": metric_name,
                "label": label,
                "resolved_rule": f"Use {label} as the revenue metric.",
                "implementation": description,
            }
        )

    return {
        "id": "q_direct_metric_ambiguity",
        "priority": "must_answer",
        "issue_summary": "The question uses the generic term revenue, which can mean billed revenue, collected revenue, or MRR.",
        "question": "When you say revenue, which metric should I use?",
        "recommended_option_id": "billed_revenue",
        "recommendation_reason": "Billed revenue is often the safest default when the question concerns generated revenue but does not mention payments or MRR.",
        "options": options,
        "allow_custom_answer": False,
    }

from __future__ import annotations

import re
from typing import Literal, TypedDict


RequestScope = Literal["single_source", "multi_source", "ambiguous"]


class RequestClassification(TypedDict):
    scope: RequestScope
    join_intent: bool
    matched_terms: list[str]
    reason: str


_MULTI_SOURCE_PATTERNS = [
    r"\bjoin\b",
    r"\bcompare\b",
    r"\breconcile\b",
    r"\bmatching?\b",
    r"\bcombine\b",
    r"\bcombines?\b",
    r"\bbetween\b",
    r"\b360\b",
    r"\brevenue\s+360\b",
    r"\bcollection\s+health\b",
    r"\bcollection\s+dashboard\b",
    r"\bcollection\s+rate\b",
    r"\boverdue\s+invoices?\b",
    r"\bunpaid\s+invoices?\b",
    r"\bpartial\s+payments?\b",
    r"\boverpayments?\b",
    r"\bbilled\s+vs\s+collected\b",
    r"\binvoices?\s+and\s+payments?\b",
    r"\bpayments?\s+and\s+invoices?\b",
    r"\bsubscriptions?,?\s+plans?,?\s+invoices?,?\s+and\s+payments?\b",
    r"\bcustomers?,?\s+subscriptions?,?\s+plans?,?\s+invoices?,?\s+and\s+payments?\b",
    r"\bwithout\s+matching\b",
    r"\bunmatched\b",
    r"\bpaid\s+invoices?\b",
    r"\bpayments?\s+without\s+invoices?\b",
    r"\binvoices?\s+without\s+payments?\b",
    r"\bcollected\s+payments?\b",
    r"\bcollected\s+revenue\b",
    r"\bby\s+customer\s+segment\s+and\s+country\b",
    r"\bby\s+country\s+and\s+product\s+family\b",
    r"\bproduct\s+family\b",
]


def classify_request_scope(prompt: str) -> RequestClassification:
    normalized = _normalize(prompt)
    matched_terms = _match_terms(normalized)

    if matched_terms:
        return {
            "scope": "multi_source",
            "join_intent": True,
            "matched_terms": matched_terms,
            "reason": (
                "The request appears to combine, compare, reconcile, enrich, or report "
                "across multiple business entities/sources."
            ),
        }

    return {
        "scope": "single_source",
        "join_intent": False,
        "matched_terms": [],
        "reason": "No explicit multi-source or join intent detected.",
    }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _match_terms(text: str) -> list[str]:
    matched: list[str] = []

    for pattern in _MULTI_SOURCE_PATTERNS:
        if re.search(pattern, text):
            human_readable = (
                pattern.strip(r"\b")
                .replace("\\s+", " ")
                .replace("\\b", "")
                .replace("\\", "")
            )
            matched.append(human_readable)

    return matched

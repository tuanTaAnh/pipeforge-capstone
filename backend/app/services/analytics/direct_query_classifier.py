from __future__ import annotations

import re
from typing import TypedDict


class DirectQueryClassification(TypedDict):
    is_direct_analytics_question: bool
    matched_terms: list[str]
    reason: str


_DIRECT_PATTERNS = [
    r"^\s*which\b",
    r"^\s*what\b",
    r"^\s*how\s+(many|much)\b",
    r"^\s*show\b",
    r"^\s*list\b",
    r"^\s*find\b",
    r"^\s*top\b",
    r"\bhighest\b",
    r"\blargest\b",
    r"\bbiggest\b",
    r"\bmost\b",
    r"\btotal\b",
    r"\bhow\s+many\b",
    r"\bhow\s+much\b",
]

_GENERATION_PATTERNS = [
    r"\bbuild\b",
    r"\bcreate\b",
    r"\bgenerate\b",
    r"\bprepare\b",
    r"\bdata\s+product\b",
    r"\bmart\b",
    r"\bmodel\b",
    r"\bdbt\b",
    r"\bdashboard\b",
]


def classify_direct_analytics_query(prompt: str) -> DirectQueryClassification:
    normalized = re.sub(r"\s+", " ", prompt.lower()).strip()
    generation_matches = _match(normalized, _GENERATION_PATTERNS)
    direct_matches = _match(normalized, _DIRECT_PATTERNS)

    if direct_matches and not generation_matches:
        return {
            "is_direct_analytics_question": True,
            "matched_terms": direct_matches,
            "reason": "The request asks for a direct analytical answer rather than a generated data product package.",
        }

    return {
        "is_direct_analytics_question": False,
        "matched_terms": direct_matches,
        "reason": (
            "The request appears to be a data product generation task or does not clearly ask "
            "for a direct database answer."
        ),
    }


def _match(text: str, patterns: list[str]) -> list[str]:
    matched: list[str] = []

    for pattern in patterns:
        if re.search(pattern, text):
            matched.append(pattern)

    return matched

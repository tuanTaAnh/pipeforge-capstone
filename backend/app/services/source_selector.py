from __future__ import annotations

import re
from typing import Any, TypedDict

from app.data.seed_demo_db import ensure_demo_database
from app.services.contract_loader import (
    get_contract_aliases,
    get_contract_source_name,
    load_all_source_contracts,
)
from app.services.database_service import table_exists


class SourceSelection(TypedDict):
    source_name: str
    contract: dict[str, Any]
    score: int
    reason: str
    available_sources: list[str]


def select_source_for_prompt(prompt: str) -> SourceSelection:
    ensure_demo_database()

    contracts = load_all_source_contracts()

    if not contracts:
        raise RuntimeError("No source contracts found in backend/app/contracts.")

    available_contracts = [
        contract
        for contract in contracts
        if table_exists(get_contract_source_name(contract))
    ]

    if not available_contracts:
        contract_names = [get_contract_source_name(contract) for contract in contracts]
        raise RuntimeError(
            "No contracted source tables exist in the database. "
            f"Contracts found={contract_names}"
        )

    available_sources = [
        get_contract_source_name(contract)
        for contract in available_contracts
    ]

    if len(available_contracts) == 1:
        contract = available_contracts[0]
        return {
            "source_name": get_contract_source_name(contract),
            "contract": contract,
            "score": 1,
            "reason": "Only one contracted source table is available.",
            "available_sources": available_sources,
        }

    scored = [
        _score_contract(prompt, contract, available_sources)
        for contract in available_contracts
    ]

    scored.sort(key=lambda item: item["score"], reverse=True)

    best = scored[0]

    if best["score"] <= 0:
        return {
            "source_name": get_contract_source_name(available_contracts[0]),
            "contract": available_contracts[0],
            "score": 0,
            "reason": (
                "No source strongly matched the prompt. "
                "Using the first available source as fallback."
            ),
            "available_sources": available_sources,
        }

    return best


def _score_contract(
    prompt: str,
    contract: dict[str, Any],
    available_sources: list[str],
) -> SourceSelection:
    source_name = get_contract_source_name(contract)

    prompt_normalized = _normalize(prompt)
    prompt_tokens = _tokens(prompt_normalized)

    aliases = get_contract_aliases(contract)

    score = 0
    matched_terms: list[str] = []

    for alias in aliases:
        alias_normalized = _normalize(alias)

        if not alias_normalized:
            continue

        alias_tokens = _tokens(alias_normalized)

        if alias_normalized in prompt_normalized:
            score += 10 + len(alias_tokens)
            matched_terms.append(alias)
            continue

        overlap = prompt_tokens.intersection(alias_tokens)
        if overlap:
            score += len(overlap)
            matched_terms.append(alias)

    source_tokens = _tokens(_normalize(source_name.replace("_", " ")))
    direct_overlap = prompt_tokens.intersection(source_tokens)
    if direct_overlap:
        score += 5 * len(direct_overlap)
        matched_terms.append(source_name)

    reason = (
        f"Matched prompt terms against aliases/source metadata: {sorted(set(matched_terms))}"
        if matched_terms
        else "No aliases or source metadata matched the prompt."
    )

    return {
        "source_name": source_name,
        "contract": contract,
        "score": score,
        "reason": reason,
        "available_sources": available_sources,
    }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()


def _tokens(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "the",
        "to",
        "as",
        "is",
        "are",
        "be",
        "by",
        "for",
        "from",
        "with",
        "and",
        "or",
        "of",
        "in",
        "on",
        "it",
        "this",
        "that",
        "should",
        "we",
        "our",
        "need",
        "needs",
        "build",
        "prepare",
        "create",
        "data",
        "dataset",
        "product",
        "pipeline",
    }

    words = re.findall(r"[a-z0-9]+", text)
    return {word for word in words if word not in stopwords and len(word) > 1}
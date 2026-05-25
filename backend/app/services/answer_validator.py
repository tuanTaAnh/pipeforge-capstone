from __future__ import annotations

import re
from typing import Any


def validate_answer(
    question: dict[str, Any],
    answer: dict[str, Any],
) -> dict[str, Any]:
    selected_option_id = answer.get("selectedOptionId") or answer.get("selected_option_id")
    custom_answer = (
        answer.get("customAnswer")
        or answer.get("custom_answer")
        or answer.get("answer")
        or ""
    ).strip()

    if selected_option_id:
        return _validate_selected_option(question, selected_option_id)

    if custom_answer:
        return _validate_custom_answer(question, custom_answer)

    return _invalid_result(
        question,
        "Please select one of the suggested options or enter a custom rule.",
    )


def _validate_selected_option(
    question: dict[str, Any],
    selected_option_id: str,
) -> dict[str, Any]:
    for option in question["options"]:
        if option["id"] == selected_option_id:
            return {
                "is_valid": True,
                "question_id": question["id"],
                "answer_type": "predefined_option",
                "selected_option_id": selected_option_id,
                "raw_answer": option["label"],
                "resolved_rule": option["resolved_rule"],
                "implementation": option["implementation"],
                "source": "user_selected",
            }

    return _invalid_result(
        question,
        f"Unknown option id: {selected_option_id}. Please choose one of the suggested options.",
    )


def _validate_custom_answer(
    question: dict[str, Any],
    custom_answer: str,
) -> dict[str, Any]:
    normalized = _normalize_text(custom_answer)

    matched_option = _match_custom_answer_to_dynamic_option(question, normalized)

    if matched_option:
        return {
            "is_valid": True,
            "question_id": question["id"],
            "answer_type": "custom_mapped_to_option",
            "selected_option_id": matched_option["id"],
            "raw_answer": custom_answer,
            "resolved_rule": matched_option["resolved_rule"],
            "implementation": matched_option["implementation"],
            "source": "user_custom_mapped",
        }

    if _looks_like_custom_rule(normalized):
        return {
            "is_valid": True,
            "question_id": question["id"],
            "answer_type": "custom",
            "selected_option_id": None,
            "raw_answer": custom_answer,
            "resolved_rule": custom_answer,
            "implementation": custom_answer,
            "source": "user_custom",
        }

    return _invalid_result(
        question,
        "I could not map your answer to a clear handling rule for this data quality issue.",
    )


def _match_custom_answer_to_dynamic_option(
    question: dict[str, Any],
    normalized_answer: str,
) -> dict[str, Any] | None:
    answer_tokens = _tokens(normalized_answer)

    if not answer_tokens:
        return None

    best_option: dict[str, Any] | None = None
    best_score = 0

    for option in question.get("options", []):
        searchable_text = " ".join(
            [
                str(option.get("id", "")),
                str(option.get("label", "")),
                str(option.get("resolved_rule", "")),
                str(option.get("implementation", "")),
            ]
        )

        option_tokens = _tokens(_normalize_text(searchable_text))

        if not option_tokens:
            continue

        overlap = len(answer_tokens.intersection(option_tokens))
        score = overlap / max(len(answer_tokens), 1)

        if score > best_score:
            best_score = score
            best_option = option

    if best_option and best_score >= 0.45:
        return best_option

    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


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
    }

    words = re.findall(r"[a-z0-9_]+", text)
    return {word for word in words if word not in stopwords and len(word) > 1}


def _looks_like_custom_rule(text: str) -> bool:
    meaningful_words = [
        "treat",
        "use",
        "set",
        "replace",
        "exclude",
        "include",
        "filter",
        "flag",
        "convert",
        "group",
        "deduplicate",
        "subtract",
        "ignore",
        "map",
        "keep",
        "remove",
        "drop",
        "calculate",
        "aggregate",
        "separate",
        "validate",
    ]

    return len(text.split()) >= 3 and any(word in text for word in meaningful_words)


def _invalid_result(question: dict[str, Any], message: str) -> dict[str, Any]:
    examples = [option["label"] for option in question.get("options", [])]

    return {
        "is_valid": False,
        "question_id": question["id"],
        "message": (
            f"{message} You can choose one of the predefined suggestions or enter a clearer custom rule."
        ),
        "examples": examples,
    }
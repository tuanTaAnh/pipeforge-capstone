from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.paths import SEMANTIC_CONTRACTS_DIR as SEMANTIC_DIR


def _load_yaml(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Semantic config file not found: {path}")
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if data is None and not required:
        return {}

    if not isinstance(data, dict):
        raise ValueError(f"Semantic config must be a YAML object: {path}")

    return data


def load_metrics() -> dict[str, dict[str, Any]]:
    data = _load_yaml(SEMANTIC_DIR / "metrics.yml")
    metrics = data.get("metrics", {})

    if not isinstance(metrics, dict):
        raise ValueError("metrics.yml must contain a metrics object.")

    return {
        str(metric_name): metric
        for metric_name, metric in metrics.items()
        if isinstance(metric, dict)
    }


def load_dimensions() -> dict[str, dict[str, Any]]:
    data = _load_yaml(SEMANTIC_DIR / "dimensions.yml")
    dimensions = data.get("dimensions", {})

    if not isinstance(dimensions, dict):
        raise ValueError("dimensions.yml must contain a dimensions object.")

    return {
        str(dimension_name): dimension
        for dimension_name, dimension in dimensions.items()
        if isinstance(dimension, dict)
    }


def load_time_semantics() -> dict[str, Any]:
    return _load_yaml(SEMANTIC_DIR / "time_semantics.yml")


def load_query_patterns() -> dict[str, Any]:
    return _load_yaml(SEMANTIC_DIR / "query_patterns.yml")


def load_clarification_rules() -> list[dict[str, Any]]:
    """Load metadata-driven business clarification rules.

    This file is optional so that the generic backend can run against databases
    that do not define custom ambiguity rules. Domain-specific concepts such as
    Stripe, revenue definitions, and adjustment-handling options belong in YAML,
    not in Python planner code.
    """
    data = _load_yaml(SEMANTIC_DIR / "clarification_rules.yml", required=False)
    rules = data.get("clarification_rules", [])

    if rules is None:
        return []

    if not isinstance(rules, list):
        raise ValueError("clarification_rules.yml must contain a clarification_rules list.")

    return [rule for rule in rules if isinstance(rule, dict)]


def load_semantic_layer() -> dict[str, Any]:
    return {
        "metrics": load_metrics(),
        "dimensions": load_dimensions(),
        "time_semantics": load_time_semantics(),
        "query_patterns": load_query_patterns(),
        "clarification_rules": load_clarification_rules(),
    }
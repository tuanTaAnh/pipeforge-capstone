from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.paths import SEMANTIC_CONTRACTS_DIR as SEMANTIC_DIR


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Semantic config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

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


def load_semantic_layer() -> dict[str, Any]:
    return {
        "metrics": load_metrics(),
        "dimensions": load_dimensions(),
        "time_semantics": load_time_semantics(),
        "query_patterns": load_query_patterns(),
    }

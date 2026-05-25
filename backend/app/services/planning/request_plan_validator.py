from __future__ import annotations

from typing import Any

from app.schemas.llm_plans import RequestPlan


VALID_REQUEST_TYPES = {"direct_analytics", "data_product_generation", "clarification", "out_of_scope"}


class PlanValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_request_plan(plan: RequestPlan, metadata_context: dict[str, Any]) -> None:
    errors: list[str] = []

    if plan.request_type not in VALID_REQUEST_TYPES:
        errors.append(f"Invalid request_type: {plan.request_type}")

    allowed_sources = set(metadata_context.get("allowed_sources", []))
    allowed_metrics = set(metadata_context.get("allowed_metrics", []))
    allowed_dimensions = set(metadata_context.get("allowed_dimensions", []))
    allowed_data_products = set(metadata_context.get("allowed_data_products", []))

    for source in plan.selected_sources:
        if source not in allowed_sources:
            errors.append(f"Unknown selected source: {source}")

    for metric in plan.selected_metrics:
        if metric not in allowed_metrics:
            errors.append(f"Unknown selected metric: {metric}")

    for dimension in plan.selected_dimensions:
        if dimension not in allowed_dimensions:
            errors.append(f"Unknown selected dimension: {dimension}")

    if plan.selected_data_product and plan.selected_data_product not in allowed_data_products:
        errors.append(f"Unknown selected data product: {plan.selected_data_product}")

    if plan.request_type in {"direct_analytics", "data_product_generation"} and not plan.selected_sources:
        if not plan.selected_data_product:
            errors.append(f"request_type={plan.request_type} requires selected_sources or selected_data_product")

    if plan.clarification_required and not plan.clarification_question:
        errors.append("clarification_required=true but clarification_question is missing")

    if plan.clarification_question:
        option_ids = [option.id for option in plan.clarification_question.options]
        if len(option_ids) != len(set(option_ids)):
            errors.append("clarification options contain duplicate ids")

    if errors:
        raise PlanValidationError(errors)


def ensure_sources_from_data_product(plan: RequestPlan, metadata_context: dict[str, Any]) -> RequestPlan:
    if plan.selected_sources or not plan.selected_data_product:
        return plan

    data_product = metadata_context.get("data_products", {}).get(plan.selected_data_product)
    if not isinstance(data_product, dict):
        return plan

    plan.selected_sources = [str(source) for source in data_product.get("sources", []) if str(source).strip()]
    return plan

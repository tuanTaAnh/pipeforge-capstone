from __future__ import annotations

from typing import Any

from app.schemas.llm_plans import ArtifactPlan, RequestPlan


_MAX_BUSINESS_INTERPRETATION_CHARS = 180
_MAX_LIST_ITEMS = 3
_MAX_LIST_ITEM_CHARS = 100


def build_data_product_artifact_plan(
    *,
    request_plan: RequestPlan,
    metadata_context: dict[str, Any],
    business_rules_context: str = "",
) -> ArtifactPlan:
    """Build a safe deterministic artifact plan from data product metadata.

    This is the fallback and baseline for Step 8B. The LLM can enrich the short
    business wording, but the file plan itself should primarily come from the
    data product contract so a JSON planner failure does not fail the whole run.
    """

    product_name = request_plan.selected_data_product or ""
    product = _get_data_product(metadata_context, product_name)
    contract_plan = _get_contract_artifact_plan(product)

    selected_sources = _string_list(request_plan.selected_sources) or _string_list(product.get("sources"))
    model_files = _string_list(contract_plan.get("model_files"))
    test_files = _string_list(contract_plan.get("test_files"))
    documentation_files = _string_list(contract_plan.get("documentation_files"))

    if not model_files:
        model_files = _default_model_files(product_name=product_name, selected_sources=selected_sources)
    if not test_files:
        test_files = ["schema.yml"]
    if not documentation_files:
        documentation_files = ["pipeline_summary.md"]

    final_mart_name = str(contract_plan.get("final_mart_name") or "").strip()
    if not final_mart_name:
        final_mart_name = _infer_final_mart_name(model_files)

    business_interpretation = _short_text(
        request_plan.business_interpretation
        or str(product.get("description") or "")
        or "Build a compact reviewed data product from selected sources.",
        max_chars=_MAX_BUSINESS_INTERPRETATION_CHARS,
    )

    assumptions = _dedupe_short_list(
        [
            *_string_list(request_plan.assumptions),
            *_business_rule_assumptions(business_rules_context),
            *_grain_assumptions(product),
        ],
        max_items=_MAX_LIST_ITEMS,
        max_chars=_MAX_LIST_ITEM_CHARS,
    )

    warnings = _dedupe_short_list(
        _string_list(request_plan.warnings),
        max_items=_MAX_LIST_ITEMS,
        max_chars=_MAX_LIST_ITEM_CHARS,
    )

    return ArtifactPlan(
        package_name=str(contract_plan.get("package_name") or product.get("package_name") or "PipeForge Data Product Draft"),
        source_name=str(contract_plan.get("source_name") or product_name or "llm_selected_sources"),
        selected_sources=selected_sources,
        final_mart_name=final_mart_name,
        model_files=model_files[:8],
        test_files=test_files[:3],
        documentation_files=documentation_files[:2],
        business_interpretation=business_interpretation,
        assumptions=assumptions,
        warnings=warnings,
    )


def _get_data_product(metadata_context: dict[str, Any], product_name: str) -> dict[str, Any]:
    data_products = metadata_context.get("data_products")
    if not isinstance(data_products, dict):
        return {}

    product = data_products.get(product_name)
    return product if isinstance(product, dict) else {}


def _get_contract_artifact_plan(product: dict[str, Any]) -> dict[str, Any]:
    plan = product.get("artifact_plan_examples") or product.get("artifact_plan") or {}
    return plan if isinstance(plan, dict) else {}


def _default_model_files(*, product_name: str, selected_sources: list[str]) -> list[str]:
    if product_name == "subscription_revenue_360":
        return [
            "stg_demo__customers.sql",
            "stg_demo__plans.sql",
            "stg_demo__subscriptions.sql",
            "stg_stripe__invoices.sql",
            "stg_stripe__payments.sql",
            "int_subscription__mrr_adjustments.sql",
            "mart_subscription__revenue_360_monthly.sql",
        ]

    staging_files = [f"stg_{source_name}.sql" for source_name in selected_sources]
    return [*staging_files, "mart_pipeforge__output.sql"] if staging_files else ["mart_pipeforge__output.sql"]


def _infer_final_mart_name(model_files: list[str]) -> str:
    mart_files = [filename for filename in model_files if filename.startswith("mart_") and filename.endswith(".sql")]
    if mart_files:
        return mart_files[-1].removesuffix(".sql")
    if model_files:
        return model_files[-1].removesuffix(".sql")
    return "mart_pipeforge__output"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _short_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _dedupe_short_list(values: list[str], *, max_items: int, max_chars: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _short_text(value, max_chars=max_chars)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= max_items:
            break

    return result


def _business_rule_assumptions(business_rules_context: str) -> list[str]:
    text = business_rules_context.lower()
    assumptions: list[str] = []

    if "gross" in text and "net" in text and "mrr" in text:
        assumptions.append("Report gross and net MRR with discount and refund adjustment columns.")
    if "discount" in text or "refund" in text:
        assumptions.append("Null discount and refund values are treated as zero.")

    return assumptions


def _grain_assumptions(product: dict[str, Any]) -> list[str]:
    grain = _string_list(product.get("grain"))
    if not grain:
        return []
    return [f"The final mart grain is {', '.join(grain)}."]
from typing import Any, Dict, List, Literal, TypedDict

from app.services.llm_client import llm_client


ArtifactKind = Literal["sql", "yaml", "markdown", "json", "text"]


class GeneratedArtifact(TypedDict):
    filename: str
    type: ArtifactKind
    content: str


    SOURCE_PROFILE_CONTEXT = """
    Source: stripe.payments
    
    Columns:
    - payment_id
    - customer_id
    - amount
    - currency
    - status
    - paid_at
    - plan_id
    - customer_segment
    - discount_amount
    - refunded_at
    
    Data quality findings:
    - discount_amount is null in 45% of rows.
    - status contains paid, failed, refunded.
    - payment_id appears unique.
    - currency contains USD, EUR, GBP.
    """


    SYSTEM_PROMPT = """
    You are PipeForge, an expert analytics engineering agent.
    
    You generate implementation-ready dbt artifacts for a data product draft.
    Return ONLY valid JSON. Do not use markdown fences.
    
    The JSON must follow this shape:
    {
      "summary": "short summary",
      "artifacts": [
        {
          "filename": "path or file name",
          "type": "sql | yaml | markdown | json | text",
          "content": "full file content"
        }
      ]
    }
    
    Rules:
    - Do not include explanations outside JSON.
    - dbt SQL should use source() and ref() where appropriate.
    - Generated artifacts should be realistic enough for analytics engineer review.
    - Include the user-selected business rule in the generated logic where relevant.
    """


def _validate_artifacts(
    data: Dict[str, Any],
    required_filenames: List[str],
) -> List[GeneratedArtifact]:
    artifacts = data.get("artifacts")

    if not isinstance(artifacts, list):
        raise RuntimeError("LLM output missing artifacts list")

    normalized: List[GeneratedArtifact] = []

    for item in artifacts:
        if not isinstance(item, dict):
            raise RuntimeError("Invalid artifact item from LLM")

        filename = item.get("filename")
        artifact_type = item.get("type")
        content = item.get("content")

        if not isinstance(filename, str) or not filename:
            raise RuntimeError("Artifact missing filename")

        if artifact_type not in {"sql", "yaml", "markdown", "json", "text"}:
            raise RuntimeError(f"Invalid artifact type for {filename}: {artifact_type}")

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Artifact {filename} has empty content")

        normalized.append(
            {
                "filename": filename,
                "type": artifact_type,
                "content": content,
            }
        )

    filenames = {artifact["filename"] for artifact in normalized}
    missing = [name for name in required_filenames if name not in filenames]

    if missing:
        raise RuntimeError(f"LLM output missing required artifacts: {missing}")

    return normalized


async def generate_model_artifacts(discount_rule: str) -> List[GeneratedArtifact]:
    user_prompt = f"""
    Business goal:
    Create a trusted monthly revenue dataset from Stripe payments for a Finance board dashboard.
    The final mart should calculate MRR by customer segment.
    
    Source profile:
    {SOURCE_PROFILE_CONTEXT}
    
    Confirmed business rule:
    Missing discount handling = {discount_rule}
    
    Generate exactly these dbt SQL files:
    1. stg_stripe__payments.sql
    2. int_payments__revenue_rules.sql
    3. mart_revenue__monthly_by_segment.sql
    
    Requirements:
    - stg_stripe__payments.sql must normalize discount_amount based on the confirmed business rule.
    - If missing discounts are treated as zero, use coalesce(discount_amount, 0).
    - int_payments__revenue_rules.sql must define net_revenue_amount and is_revenue_eligible.
    - Failed payments should not count as revenue.
    - Refunded payments should reduce revenue.
    - mart_revenue__monthly_by_segment.sql should aggregate monthly_recurring_revenue by revenue_month, customer_segment, and currency.
    """

    data = await llm_client.generate_json(SYSTEM_PROMPT, user_prompt, max_output_tokens=5000)

    return _validate_artifacts(
        data,
        [
            "stg_stripe__payments.sql",
            "int_payments__revenue_rules.sql",
            "mart_revenue__monthly_by_segment.sql",
        ],
    )


async def generate_test_artifacts(discount_rule: str) -> List[GeneratedArtifact]:
    user_prompt = f"""
    Business goal:
    Create dbt tests for a Stripe MRR data product.
    
    Source profile:
    {SOURCE_PROFILE_CONTEXT}
    
    Confirmed business rule:
    Missing discount handling = {discount_rule}
    
    Generate exactly these files:
    1. schema.yml
    2. custom_tests/test_mrr_not_null.sql
    
    Requirements:
    - schema.yml should include model descriptions and column tests.
    - Include tests for payment_id uniqueness, not_null checks, accepted_values for status, and final mart metric quality.
    - custom_tests/test_mrr_not_null.sql should check that monthly_recurring_revenue is not null in the final mart.
    """

    data = await llm_client.generate_json(SYSTEM_PROMPT, user_prompt, max_output_tokens=4000)

    return _validate_artifacts(
        data,
        [
            "schema.yml",
            "custom_tests/test_mrr_not_null.sql",
        ],
    )


async def generate_doc_artifacts(discount_rule: str) -> List[GeneratedArtifact]:
    user_prompt = f"""
    Business goal:
    Document a Stripe Revenue Data Product Draft for analytics review.
    
    Source profile:
    {SOURCE_PROFILE_CONTEXT}
    
    Confirmed business rule:
    Missing discount handling = {discount_rule}
    
    Generate exactly this file:
    1. pipeline_summary.md
    
    Requirements:
    - Explain the purpose of the data product.
    - Name the final mart: mart_revenue__monthly_by_segment.
    - Explain metrics, dimensions, assumptions, and next steps.
    - Mention that analytics engineers should review, copy files into dbt, run dbt build/dbt test, then connect the final mart to BI.
    """

    data = await llm_client.generate_json(SYSTEM_PROMPT, user_prompt, max_output_tokens=3000)

    return _validate_artifacts(
        data,
        [
            "pipeline_summary.md",
        ],
    )
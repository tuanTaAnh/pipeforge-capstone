from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


RequestType = Literal["direct_analytics", "data_product_generation", "clarification", "out_of_scope"]


class PlannerOption(BaseModel):
    id: str
    label: str
    description: str | None = None
    resolved_rule: str | None = None
    implementation: str | None = None


class PlannerQuestion(BaseModel):
    id: str = "q_llm_clarification"
    question: str
    issue_summary: str | None = None
    priority: str = "must_answer"
    recommended_option_id: str | None = None
    recommendation_reason: str | None = None
    options: list[PlannerOption] = Field(default_factory=list)
    allow_custom_answer: bool = True


class RequestPlan(BaseModel):
    request_type: RequestType
    clarification_required: bool = False
    clarification_question: PlannerQuestion | None = None
    selected_sources: list[str] = Field(default_factory=list)
    selected_metrics: list[str] = Field(default_factory=list)
    selected_dimensions: list[str] = Field(default_factory=list)
    selected_data_product: str | None = None
    business_interpretation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reasoning_summary: str | None = None

    @field_validator("selected_sources", "selected_metrics", "selected_dimensions", "assumptions", "warnings", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


class DirectQueryPlan(BaseModel):
    sql: str
    business_interpretation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("assumptions", "warnings", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


class BusinessDecisionPlan(BaseModel):
    clarification_required: bool = False
    questions: list[PlannerQuestion] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ArtifactPlan(BaseModel):
    package_name: str = "PipeForge Data Product Draft"
    source_name: str | None = None
    selected_sources: list[str] = Field(default_factory=list)
    final_mart_name: str = "mart_pipeforge__output"
    model_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    documentation_files: list[str] = Field(default_factory=list)
    business_interpretation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)

    @field_validator("selected_sources", "model_files", "test_files", "documentation_files", "assumptions", "warnings", "generation_notes", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def as_artifact_plan_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["source_name"] = data.get("source_name") or (self.selected_sources[0] if self.selected_sources else "llm_selected_sources")
        return data

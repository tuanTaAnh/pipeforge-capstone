from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from app.schemas.artifacts import Artifact
from app.schemas.events import AgentEvent


class StartRunRequest(BaseModel):
    prompt: str


class StartRunResponse(BaseModel):
    runId: str


class AskUserOption(BaseModel):
    id: str
    label: str
    resolved_rule: Optional[str] = None
    implementation: Optional[str] = None


class AskUserQuestion(BaseModel):
    questionId: str
    question: str
    options: List[AskUserOption]
    issueSummary: Optional[str] = None
    priority: Literal["must_answer", "optional_review"] = "must_answer"
    recommendedOptionId: Optional[str] = None
    recommendationReason: Optional[str] = None
    allowCustomAnswer: bool = True
    validationError: Optional[str] = None


class AnswerRequest(BaseModel):
    questionId: str
    answer: Optional[str] = None
    selectedOptionId: Optional[str] = None
    customAnswer: Optional[str] = None


class RetryRequest(BaseModel):
    agentId: Optional[str] = None


class RunSnapshot(BaseModel):
    runId: str
    prompt: str
    status: str
    events: List[AgentEvent]
    artifacts: List[Artifact]
    pendingQuestion: Optional[AskUserQuestion] = None
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.artifacts import Artifact
from app.schemas.events import AgentEvent


class StartRunRequest(BaseModel):
    prompt: str


class StartRunResponse(BaseModel):
    runId: str


class AskUserQuestion(BaseModel):
    questionId: str
    question: str
    options: List[str]


class AnswerRequest(BaseModel):
    questionId: str
    answer: str


class RetryRequest(BaseModel):
    agentId: Optional[str] = None


class RunSnapshot(BaseModel):
    runId: str
    prompt: str
    status: str
    events: List[AgentEvent]
    artifacts: List[Artifact]
    pendingQuestion: Optional[AskUserQuestion] = None
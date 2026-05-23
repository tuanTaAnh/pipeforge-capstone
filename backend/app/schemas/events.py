from typing import Any, Dict, Literal

from pydantic import BaseModel

from app.schemas.agents import AgentInfo


EventType = Literal[
    "session_started",
    "agent_started",
    "agent_thinking",
    "tool_started",
    "tool_completed",
    "sub_agent_started",
    "sub_agent_completed",
    "agent_response",
    "ask_user",
    "ask_user_answered",
    "artifact_created",
    "final_message",
    "agent_completed",
    "agent_failed",
    "error",
    "done",
]


class AgentEvent(BaseModel):
    id: str
    seq: int
    runId: str
    type: EventType
    timestamp: str
    agent: AgentInfo
    payload: Dict[str, Any] = {}
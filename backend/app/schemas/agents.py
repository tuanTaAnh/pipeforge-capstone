from typing import Literal, Optional

from pydantic import BaseModel


AgentRole = Literal["orchestrator", "sub_agent"]


class AgentInfo(BaseModel):
    id: str
    name: str
    role: AgentRole
    parentId: Optional[str] = None
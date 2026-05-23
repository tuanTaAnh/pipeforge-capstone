from typing import Literal

from pydantic import BaseModel


ArtifactType = Literal["sql", "yaml", "markdown", "json", "text"]


class Artifact(BaseModel):
    id: str
    runId: str
    filename: str
    path: str
    type: ArtifactType
    createdByAgentId: str
    createdByAgentName: str
    contentPreview: str
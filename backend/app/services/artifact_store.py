from pathlib import Path

from app.core.config import settings
from app.schemas.agents import AgentInfo
from app.schemas.artifacts import Artifact, ArtifactType
from app.services.event_emitter import event_emitter
from app.services.run_registry import registry
from app.utils.ids import make_id


class ArtifactStore:
    async def write_artifact(
        self,
        run_id: str,
        agent: AgentInfo,
        filename: str,
        content: str,
        artifact_type: ArtifactType,
    ) -> Artifact:
        artifact_id = make_id("art")

        run_dir = settings.workspace_path / run_id
        file_path = run_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        artifact = Artifact(
            id=artifact_id,
            runId=run_id,
            filename=filename,
            path=str(file_path),
            type=artifact_type,
            createdByAgentId=agent.id,
            createdByAgentName=agent.name,
            contentPreview=content[:1000],
        )

        registry.runs[run_id]["artifacts"][artifact_id] = artifact.model_dump()

        await event_emitter.emit(
            run_id=run_id,
            event_type="artifact_created",
            agent=agent,
            payload=artifact.model_dump(),
        )

        return artifact

    def get_artifact_content(self, run_id: str, artifact_id: str) -> str:
        artifact = registry.runs[run_id]["artifacts"].get(artifact_id)
        if not artifact:
            raise FileNotFoundError("Artifact not found")

        path = Path(artifact["path"])
        if not path.exists():
            raise FileNotFoundError("Artifact file missing")

        return path.read_text(encoding="utf-8")


artifact_store = ArtifactStore()
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.artifact_store import artifact_store
from app.services.run_registry import registry

router = APIRouter(prefix="/api/runs", tags=["artifacts"])


@router.get("/{run_id}/artifacts/{artifact_id}")
async def get_artifact(run_id: str, artifact_id: str) -> PlainTextResponse:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        content = artifact_store.get_artifact_content(run_id, artifact_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PlainTextResponse(content)
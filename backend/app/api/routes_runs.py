import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.runs import RetryRequest, RunSnapshot, StartRunRequest, StartRunResponse
from app.services.event_store import event_store
from app.services.pipeforge_workflow_runner import PIPELINE_ARCHITECT, run_pipeforge_workflow
from app.services.event_emitter import event_emitter
from app.services.run_registry import registry

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=StartRunResponse)
async def start_run(request: StartRunRequest) -> StartRunResponse:
    run_id = registry.create_run(request.prompt)
    asyncio.create_task(run_pipeforge_workflow(run_id, request.prompt))
    return StartRunResponse(runId=run_id)


@router.get("/{run_id}", response_model=RunSnapshot)
async def get_run(run_id: str) -> RunSnapshot:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    run = registry.get_run(run_id)
    return RunSnapshot(
        runId=run_id,
        prompt=run["prompt"],
        status=run["status"],
        events=run["events"],
        artifacts=list(run["artifacts"].values()),
        pendingQuestion=run["pendingQuestion"],
    )


@router.get("/{run_id}/events")
async def stream_events(run_id: str, after: int = 0) -> StreamingResponse:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        last_seq = after

        while True:
            run = registry.get_run(run_id)

            pending_events = event_store.get_after(run_id, last_seq)
            for event in pending_events:
                last_seq = event["seq"]
                yield f"id: {event['seq']}\n"
                yield "event: message\n"
                yield f"data: {json.dumps(event)}\n\n"

            if run["status"] in {"completed", "failed"} and last_seq >= event_store.count(run_id):
                break

            async with registry.conditions[run_id]:
                try:
                    await asyncio.wait_for(registry.conditions[run_id].wait(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{run_id}/retry")
async def retry_run(run_id: str, request: RetryRequest) -> dict:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    await event_emitter.emit(
        run_id,
        "agent_response",
        PIPELINE_ARCHITECT,
        {
            "text": "Retry requested. In this MVP, retry is recorded as a recovery action. A production version would rerun the selected failed agent with the stored context."
        },
    )

    return {"status": "retry-recorded", "agentId": request.agentId}
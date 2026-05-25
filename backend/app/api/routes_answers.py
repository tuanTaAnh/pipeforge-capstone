from fastapi import APIRouter, HTTPException

from app.schemas.runs import AnswerRequest
from app.services.decisions.answer_queue import answer_queue
from app.services.runtime.run_registry import registry

router = APIRouter(prefix="/api/runs", tags=["answers"])


@router.post("/{run_id}/answers")
async def submit_answer(run_id: str, request: AnswerRequest) -> dict:
    if not registry.exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        answer_queue.submit_answer(
            run_id=run_id,
            question_id=request.questionId,
            answer=request.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "accepted"}
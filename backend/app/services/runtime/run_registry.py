import asyncio
from typing import Any, Dict

from app.utils.ids import make_id


class RunRegistry:
    def __init__(self) -> None:
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.conditions: Dict[str, asyncio.Condition] = {}
        self.locks: Dict[str, asyncio.Lock] = {}

    def create_run(self, prompt: str) -> str:
        run_id = make_id("run")
        self.runs[run_id] = {
            "runId": run_id,
            "prompt": prompt,
            "status": "created",
            "events": [],
            "artifacts": {},
            "pendingQuestion": None,
            "answerFuture": None,
            "sourceProfile": None,
            "plannedQuestions": [],
            "currentQuestionIndex": 0,
            "resolvedRules": [],
            "artifactPlan": {},
            "pipelineRun": None,
        }
        self.conditions[run_id] = asyncio.Condition()
        self.locks[run_id] = asyncio.Lock()
        return run_id

    def exists(self, run_id: str) -> bool:
        return run_id in self.runs

    def get_run(self, run_id: str) -> Dict[str, Any]:
        return self.runs[run_id]

    def set_status(self, run_id: str, status: str) -> None:
        self.runs[run_id]["status"] = status


registry = RunRegistry()
from typing import List

from app.schemas.events import AgentEvent
from app.services.runtime.run_registry import registry


class EventStore:
    async def append(self, event: AgentEvent) -> None:
        run_id = event.runId
        async with registry.locks[run_id]:
            registry.runs[run_id]["events"].append(event.model_dump())

        async with registry.conditions[run_id]:
            registry.conditions[run_id].notify_all()

    def next_seq(self, run_id: str) -> int:
        return len(registry.runs[run_id]["events"]) + 1

    def get_after(self, run_id: str, seq: int) -> List[dict]:
        return [event for event in registry.runs[run_id]["events"] if event["seq"] > seq]

    def count(self, run_id: str) -> int:
        return len(registry.runs[run_id]["events"])


event_store = EventStore()
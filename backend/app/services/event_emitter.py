from typing import Any, Dict, Optional

from app.schemas.agents import AgentInfo
from app.schemas.events import AgentEvent, EventType
from app.services.event_store import event_store
from app.utils.ids import make_id
from app.utils.time import utcnow


class EventEmitter:
    async def emit(
        self,
        run_id: str,
        event_type: EventType,
        agent: AgentInfo,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AgentEvent:
        event = AgentEvent(
            id=make_id("evt"),
            seq=event_store.next_seq(run_id),
            runId=run_id,
            type=event_type,
            timestamp=utcnow(),
            agent=agent,
            payload=payload or {},
        )
        await event_store.append(event)
        return event


event_emitter = EventEmitter()
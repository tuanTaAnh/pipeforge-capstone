from typing import Any, Dict, Optional

from app.schemas.agents import AgentInfo
from app.schemas.events import AgentEvent, EventType
from app.services.runtime.event_store import event_store
from app.services.runtime.flow_logger import flow_log
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

        # Cross-cutting observability: log every normalized event that is streamed to FE.
        # This keeps Docker logs useful even when the UI only shows part of the trace.
        flow_log(
            run_id=run_id,
            step_id="X",
            step_name="Stream event to FE",
            event=str(event_type),
            status="completed" if event_type not in {"error", "agent_failed"} else "failed",
            details={
                "event_id": event.id,
                "seq": event.seq,
                "agent_id": agent.id,
                "agent_name": agent.name,
                "agent_role": agent.role,
                "payload": payload or {},
            },
        )

        await event_store.append(event)
        return event


event_emitter = EventEmitter()

import json

from typing import Any, Dict, Optional

from app.schemas.agents import AgentInfo
from app.schemas.events import AgentEvent, EventType
from app.services.runtime.event_store import event_store
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
        if event_type in {"ask_user", "ask_user_answered", "error"}:
            print(
                "[PF DEBUG][event_emitter]",
                json.dumps(
                    {
                        "run_id": run_id,
                        "event_type": event_type,
                        "agent": agent.name,
                        "payload": payload or {},
                    },
                    ensure_ascii=False,
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        await event_store.append(event)
        return event


event_emitter = EventEmitter()
import pytest

from app.schemas.agents import AgentInfo
from app.services.event_emitter import event_emitter
from app.services.event_store import event_store
from app.services.run_registry import registry


@pytest.mark.asyncio
async def test_events_are_appended_with_increasing_seq():
    run_id = registry.create_run("test prompt")
    agent = AgentInfo(
        id="pipeline-architect",
        name="Pipeline Architect",
        role="orchestrator",
    )

    event1 = await event_emitter.emit(run_id, "session_started", agent, {})
    event2 = await event_emitter.emit(run_id, "agent_started", agent, {})

    assert event1.seq == 1
    assert event2.seq == 2
    assert event_store.count(run_id) == 2


@pytest.mark.asyncio
async def test_get_events_after_seq():
    run_id = registry.create_run("test prompt")
    agent = AgentInfo(
        id="pipeline-architect",
        name="Pipeline Architect",
        role="orchestrator",
    )

    await event_emitter.emit(run_id, "session_started", agent, {})
    await event_emitter.emit(run_id, "agent_started", agent, {})
    await event_emitter.emit(run_id, "agent_thinking", agent, {"text": "thinking"})

    events = event_store.get_after(run_id, 1)

    assert len(events) == 2
    assert events[0]["seq"] == 2
    assert events[1]["seq"] == 3
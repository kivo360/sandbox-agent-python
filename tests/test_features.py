"""Tests for session event listeners, transcript, async context manager, and CLI."""

from __future__ import annotations

import pytest
import respx
from respx import MockRouter

from sandboxagent import SandboxAgent

BASE_URL = "http://localhost:2468"


@pytest.fixture
def mock_api() -> MockRouter:
    with respx.mock(base_url=BASE_URL, assert_all_mocked=False) as router:
        yield router


class TestOnSessionEvent:
    """Test global session event listener registry."""

    async def test_register_and_fire(self, mock_api: MockRouter) -> None:
        """Listener registered via on_session_event should be tracked."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)
        events: list[dict] = []

        def listener(msg: dict) -> None:
            events.append(msg)

        unsub = agent.on_session_event("sess-1", listener)
        assert callable(unsub)
        assert "sess-1" in agent._event_listeners
        assert listener in agent._event_listeners["sess-1"]

        unsub()
        assert "sess-1" not in agent._event_listeners

        await agent.dispose()

    async def test_multiple_listeners(self, mock_api: MockRouter) -> None:
        """Multiple listeners for same session should all be tracked."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)

        def l1(msg: dict) -> None: ...
        def l2(msg: dict) -> None: ...

        unsub1 = agent.on_session_event("sess-1", l1)
        unsub2 = agent.on_session_event("sess-1", l2)

        assert len(agent._event_listeners["sess-1"]) == 2

        unsub1()
        assert len(agent._event_listeners["sess-1"]) == 1

        unsub2()
        assert "sess-1" not in agent._event_listeners

        await agent.dispose()


class TestSessionTranscript:
    """Test event tracking and transcript generation."""

    async def test_track_events_and_transcript(self, mock_api: MockRouter) -> None:
        """track_events should capture messages and get_transcript should format them."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)

        from sandboxagent.types import SessionRecord
        from sandboxagent.client import Session

        record = SessionRecord(
            id="sess-test",
            agent="mock",
            agent_session_id="agent-1",
            last_connection_id="conn-1",
            created_at=1234567890,
            destroyed_at=None,
        )
        session = Session(sandbox=agent, record=record, acp_client=None)

        # Initially no events
        assert session.get_transcript() == "(no events recorded)"

        # Enable tracking and simulate events
        session.track_events(True)
        session._events.append({"timestamp": 1234567890, "role": "user", "content": "hello"})
        session._events.append({"timestamp": 1234567891, "role": "agent", "content": "hi there"})

        transcript = session.get_transcript()
        assert "Session sess-test transcript" in transcript
        assert "[2009-02-13 23:31:30] user: hello" in transcript
        assert "[2009-02-13 23:31:31] agent: hi there" in transcript

        # Max events limit
        long_transcript = session.get_transcript(max_events=1)
        assert "user: hello" not in long_transcript
        assert "agent: hi there" in long_transcript

        await agent.dispose()

    async def test_track_events_disabled(self, mock_api: MockRouter) -> None:
        """When tracking is disabled, events should not be captured."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)

        from sandboxagent.types import SessionRecord
        from sandboxagent.client import Session

        record = SessionRecord(
            id="sess-test",
            agent="mock",
            agent_session_id="agent-1",
            last_connection_id="conn-1",
            created_at=1234567890,
            destroyed_at=None,
        )
        session = Session(sandbox=agent, record=record, acp_client=None)

        session.track_events(False)
        assert not session._track_events

        await agent.dispose()


class TestAsyncContextManager:
    """Test async context manager support."""

    async def test_aenter_aexit(self, mock_api: MockRouter) -> None:
        """SandboxAgent should support async with after creation."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)

        async with agent:
            health = await agent.health()
            assert health["status"] == "ok"

        assert agent._disposed

    async def test_aexit_on_exception(self, mock_api: MockRouter) -> None:
        """Agent should still dispose when exception is raised inside async with."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL)

        with pytest.raises(ValueError, match="boom"):
            async with agent:
                raise ValueError("boom")

        assert agent._disposed


class TestNewMethods:
    """Test recently added SandboxAgent methods."""

    async def test_get_agent(self, mock_api: MockRouter) -> None:
        """get_agent should fetch single agent info."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})
        mock_api.get("/v1/agents/claude").respond(200, json={"id": "claude", "installed": True})

        agent = await SandboxAgent.connect(BASE_URL)
        info = await agent.get_agent("claude")
        assert info["id"] == "claude"
        assert info["installed"] is True

        await agent.dispose()

    async def test_set_mcp_config(self, mock_api: MockRouter) -> None:
        """set_mcp_config should PUT config to global endpoint."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})
        route = mock_api.put("/v1/config/mcp").respond(204)

        agent = await SandboxAgent.connect(BASE_URL)
        await agent.set_mcp_config({"servers": []})

        assert route.called
        await agent.dispose()

    async def test_set_skills_config(self, mock_api: MockRouter) -> None:
        """set_skills_config should PUT config to global endpoint."""
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})
        route = mock_api.put("/v1/config/skills").respond(204)

        agent = await SandboxAgent.connect(BASE_URL)
        await agent.set_skills_config({"skills": []})

        assert route.called
        await agent.dispose()

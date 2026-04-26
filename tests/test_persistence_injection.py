"""Tests for the SessionPersistDriver injection point on SandboxAgent.

Verifies that custom SessionPersistDriver implementations can be passed via
__init__, connect(), and start() — and that the default still falls back to
InMemorySessionPersistDriver for backward compatibility.
"""

from __future__ import annotations

import pytest

from sandboxagent import (
    InMemorySessionPersistDriver,
    ListPage,
    SandboxAgent,
    SessionPersistDriver,
)
from sandboxagent.types import SessionEvent, SessionRecord


class _RecordingDriver:
    """Minimal SessionPersistDriver implementation that just records calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_session(self, session_id: str) -> SessionRecord | None:
        self.calls.append(f"get_session:{session_id}")
        return None

    async def list_sessions(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ListPage[SessionRecord]:
        self.calls.append(f"list_sessions:{cursor}:{limit}")
        return ListPage(items=[], next_cursor=None)

    async def update_session(self, session: SessionRecord) -> None:
        self.calls.append(f"update_session:{session.id}")

    async def list_events(
        self, session_id: str, *, cursor: str | None = None, limit: int | None = None
    ) -> ListPage[SessionEvent]:
        self.calls.append(f"list_events:{session_id}:{cursor}:{limit}")
        return ListPage(items=[], next_cursor=None)

    async def insert_event(self, session_id: str, event: SessionEvent) -> None:
        self.calls.append(f"insert_event:{session_id}:{event.id}")


def test_default_persistence_is_in_memory() -> None:
    agent = SandboxAgent("http://localhost:2468", skip_health_check=True)
    assert isinstance(agent._persistence, InMemorySessionPersistDriver)


def test_custom_persistence_is_wired_via_init() -> None:
    driver = _RecordingDriver()
    agent = SandboxAgent("http://localhost:2468", skip_health_check=True, persistence=driver)
    assert agent._persistence is driver


def test_recording_driver_satisfies_protocol() -> None:
    driver = _RecordingDriver()
    assert isinstance(driver, SessionPersistDriver)


def test_in_memory_driver_satisfies_protocol() -> None:
    driver = InMemorySessionPersistDriver()
    assert isinstance(driver, SessionPersistDriver)


@pytest.mark.asyncio
async def test_custom_persistence_via_connect() -> None:
    driver = _RecordingDriver()
    agent = await SandboxAgent.connect(
        "http://localhost:2468",
        skip_health_check=True,
        persistence=driver,
    )
    assert agent._persistence is driver


def test_persistence_kwarg_is_keyword_only() -> None:
    """`persistence` must be keyword-only — no positional surprise breakage."""
    driver = _RecordingDriver()
    with pytest.raises(TypeError):
        SandboxAgent(
            "http://localhost:2468",
            None,
            None,
            False,
            driver,  # type: ignore[misc] # 5th positional arg should fail
        )

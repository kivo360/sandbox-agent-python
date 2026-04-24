"""In-memory session persistence driver."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from typing import Generic, TypeVar

from sandboxagent.types import SessionEvent, SessionRecord

T = TypeVar("T")

DEFAULT_MAX_SESSIONS = 1024
DEFAULT_MAX_EVENTS_PER_SESSION = 500
DEFAULT_LIST_LIMIT = 100
DEFAULT_REPLAY_MAX_CHARS = 100_000
DEFAULT_REPLAY_MAX_EVENTS = 100


class ListPage(Generic[T]):
    """A page of items from a paginated list."""

    def __init__(self, items: list[T], next_cursor: str | None = None) -> None:
        self.items = items
        self.next_cursor = next_cursor


class InMemorySessionPersistDriver:
    """In-memory implementation of SessionPersistDriver for testing and simple use cases."""

    def __init__(
        self,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_events_per_session: int = DEFAULT_MAX_EVENTS_PER_SESSION,
    ) -> None:
        self._max_sessions = _normalize_cap(max_sessions, DEFAULT_MAX_SESSIONS)
        self._max_events_per_session = _normalize_cap(
            max_events_per_session, DEFAULT_MAX_EVENTS_PER_SESSION
        )
        self._sessions: dict[str, SessionRecord] = {}
        self._events_by_session: dict[str, list[SessionEvent]] = {}
        # Event index tracking for atomic index allocation
        self._next_event_index_by_session: dict[str, int] = {}
        self._event_index_locks: dict[str, asyncio.Lock] = {}

    async def get_session(self, session_id: str) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        return _clone_session_record(session) if session else None

    async def list_sessions(
        self, *, cursor: str | None = None, limit: int | None = None
    ) -> ListPage[SessionRecord]:
        sorted_sessions = sorted(
            self._sessions.values(),
            key=lambda s: (s.created_at, s.id),
        )
        return _paginate([_clone_session_record(s) for s in sorted_sessions], cursor=cursor, limit=limit)

    async def update_session(self, session: SessionRecord) -> None:
        self._sessions[session.id] = _clone_session_record(session)

        if session.id not in self._events_by_session:
            self._events_by_session[session.id] = []

        if len(self._sessions) <= self._max_sessions:
            return

        overflow = len(self._sessions) - self._max_sessions
        removable = sorted(
            self._sessions.values(),
            key=lambda s: (s.created_at, s.id),
        )[:overflow]

        for session_to_remove in removable:
            sid = session_to_remove.id
            del self._sessions[sid]
            self._events_by_session.pop(sid, None)

    async def list_events(
        self, session_id: str, *, cursor: str | None = None, limit: int | None = None
    ) -> ListPage[SessionEvent]:
        all_events = sorted(
            self._events_by_session.get(session_id, []),
            key=lambda e: (e.event_index, e.id),
        )
        return _paginate([_clone_session_event(e) for e in all_events], cursor=cursor, limit=limit)

    async def insert_event(self, session_id: str, event: SessionEvent) -> None:
        events = self._events_by_session.get(session_id, [])
        events.append(_clone_session_event(event))

        if len(events) > self._max_events_per_session:
            events = events[-self._max_events_per_session :]

        self._events_by_session[session_id] = events

    async def create_event_index(self, session_id: str) -> int:
        """Allocate the next event index for a session atomically.

        Args:
            session_id: The session ID to allocate an index for.

        Returns:
            The allocated event index.
        """
        # Get or create lock for this session
        if session_id not in self._event_index_locks:
            self._event_index_locks[session_id] = asyncio.Lock()
        lock = self._event_index_locks[session_id]

        async with lock:
            # Initialize if needed
            if session_id not in self._next_event_index_by_session:
                # Seed from existing events
                existing_events = self._events_by_session.get(session_id, [])
                max_index = 0
                for event in existing_events:
                    if hasattr(event, 'event_index') and event.event_index > max_index:
                        max_index = event.event_index
                    elif isinstance(event, dict) and event.get('event_index', 0) > max_index:
                        max_index = event.get('event_index', 0)
                self._next_event_index_by_session[session_id] = max_index + 1

            index = self._next_event_index_by_session[session_id]
            self._next_event_index_by_session[session_id] = index + 1
            return index

    async def persist_event(self, session_id: str, event: SessionEvent) -> None:
        """Persist a session event.

        This is an alias for insert_event with a more descriptive name.

        Args:
            session_id: The session ID.
            event: The event to persist.
        """
        await self.insert_event(session_id, event)

    async def build_replay_text(
        self,
        session_id: str,
        *,
        max_events: int = DEFAULT_REPLAY_MAX_EVENTS,
        max_chars: int = DEFAULT_REPLAY_MAX_CHARS,
        event_filter: Callable[[SessionEvent], bool] | None = None,
    ) -> str | None:
        """Build replay text from session events.

        Args:
            session_id: The session ID to build replay for.
            max_events: Maximum number of events to include.
            max_chars: Maximum characters for the replay text.
            event_filter: Optional filter function for events.

        Returns:
            Replay text string or None if no events match.
        """
        # Get all events for the session
        events_page = await self.list_events(session_id)
        all_events = events_page.items

        # Apply filter if provided
        if event_filter:
            all_events = [e for e in all_events if event_filter(e)]

        # Take the most recent events up to max_events
        events = all_events[-max_events:] if len(all_events) > max_events else all_events

        if not events:
            return None

        # Build replay text
        prefix = 'Previous session history is replayed below as JSON-RPC envelopes. Use it as context before responding to the latest user prompt.\n'
        text = prefix

        for event in events:
            # Extract event data
            created_at = getattr(event, 'created_at', 0)
            sender = getattr(event, 'sender', 'unknown')
            payload = getattr(event, 'payload', {})

            # Handle dict-style events
            if isinstance(event, dict):
                created_at = event.get('created_at', created_at)
                sender = event.get('sender', sender)
                payload = event.get('payload', payload)

            line = json.dumps({
                'createdAt': created_at,
                'sender': sender,
                'payload': payload,
            })

            if len(text) + len(line) + 1 > max_chars:
                text += '\n[history truncated]'
                break

            text += f'{line}\n'

        return text


def _normalize_cap(value: int | None, fallback: int) -> int:
    if value is None or value < 1:
        return fallback
    return int(value)


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        parsed = int(cursor)
        return parsed if parsed >= 0 else 0
    except (ValueError, TypeError):
        return 0


def _paginate(items: list[T], *, cursor: str | None = None, limit: int | None = None) -> ListPage[T]:
    offset = _parse_cursor(cursor)
    page_limit = _normalize_cap(limit, DEFAULT_LIST_LIMIT)
    page_items = items[offset : offset + page_limit]
    next_offset = offset + len(page_items)
    return ListPage(
        items=page_items,
        next_cursor=str(next_offset) if next_offset < len(items) else None,
    )


def _clone_session_record(session: SessionRecord) -> SessionRecord:
    return copy.deepcopy(session)


def _clone_session_event(event: SessionEvent) -> SessionEvent:
    return copy.deepcopy(event)

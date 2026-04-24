"""Tests for SSE streaming utilities."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from sandboxagent.sse_streaming import (
    ProcessLogSubscription,
    _parse_log_sse_chunk,
    follow_process_logs,
)


class TestParseLogSseChunk:
    """Test SSE chunk parsing."""

    def test_empty_chunk(self) -> None:
        """Empty chunk returns None."""
        assert _parse_log_sse_chunk("") is None

    def test_comment_only(self) -> None:
        """Comment-only chunk returns None."""
        assert _parse_log_sse_chunk(":this is a comment") is None

    def test_non_log_event(self) -> None:
        """Non-log events return None."""
        chunk = "event: heartbeat\ndata: {}"
        assert _parse_log_sse_chunk(chunk) is None

    def test_log_event(self) -> None:
        """Log event returns parsed data."""
        chunk = "event: log\ndata: {\"message\": \"hello\"}"
        result = _parse_log_sse_chunk(chunk)
        assert result == {"message": "hello"}

    def test_multiline_data(self) -> None:
        """Multi-line data is joined."""
        chunk = "event: log\ndata: {\"a\":\ndata: 1}"
        result = _parse_log_sse_chunk(chunk)
        assert result == {"a": 1}

    def test_invalid_json(self) -> None:
        """Invalid JSON returns None."""
        chunk = "event: log\ndata: not-json"
        assert _parse_log_sse_chunk(chunk) is None


class TestProcessLogSubscription:
    """Test ProcessLogSubscription."""

    def test_close_calls_close_fn(self) -> None:
        """close() calls the close function."""
        close_fn = MagicMock()
        closed_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        sub = ProcessLogSubscription(close_fn, closed_future)

        sub.close()
        close_fn.assert_called_once()

    def test_closed_property(self) -> None:
        """closed returns the future."""
        close_fn = MagicMock()
        closed_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        sub = ProcessLogSubscription(close_fn, closed_future)

        assert sub.closed is closed_future


class TestFollowProcessLogs:
    """Test follow_process_logs."""

    @pytest.mark.asyncio
    async def test_follow_process_logs(self) -> None:
        """Test following process logs via SSE."""
        logs: list[dict[str, Any]] = []

        def listener(entry: dict[str, Any]) -> None:
            logs.append(entry)

        # Mock transport that yields SSE data
        mock_transport = MagicMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.aiter_text = AsyncMock(return_value=aiter_text_mock())
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_transport.stream = MagicMock(return_value=mock_response)

        sub = await follow_process_logs(
            mock_transport,
            "http://localhost:2468",
            "process-123",
            listener,
        )

        assert isinstance(sub, ProcessLogSubscription)
        sub.close()


def aiter_text_mock():
    """Create an async iterator that yields SSE chunks."""
    chunks = [
        "event: log\ndata: {\"message\": \"hello\"}\n\n",
        "event: log\ndata: {\"message\": \"world\"}\n\n",
    ]
    for chunk in chunks:
        yield chunk

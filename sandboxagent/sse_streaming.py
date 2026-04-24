"""SSE streaming utilities for sandbox-agent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from sandboxagent.http import SandboxAgentError

ProcessLogListener = Callable[[dict[str, Any]], None]


class ProcessLogSubscription:
    """Subscription to a process log SSE stream."""

    def __init__(self, close_fn: Callable[[], None], closed_future: asyncio.Future[None]) -> None:
        self._close = close_fn
        self._closed = closed_future

    def close(self) -> None:
        """Close the subscription and stop receiving logs."""
        self._close()

    @property
    def closed(self) -> asyncio.Future[None]:
        """Future that completes when the subscription is fully closed."""
        return self._closed


async def follow_process_logs(
    transport: httpx.AsyncClient,
    base_url: str,
    process_id: str,
    listener: ProcessLogListener,
    *,
    token: str | None = None,
    query: dict[str, Any] | None = None,
) -> ProcessLogSubscription:
    """Follow process logs via SSE streaming.

    Args:
        transport: HTTP client to use for the request.
        base_url: Base URL of the sandbox-agent server.
        process_id: ID of the process to follow.
        listener: Callback for each log entry.
        token: Optional authentication token.
        query: Optional query parameters (e.g., follow=True).

    Returns:
        A subscription that can be closed to stop following logs.
    """
    from urllib.parse import urlencode

    params: dict[str, Any] = {"follow": "true"}
    if query:
        params.update(query)

    url = f"{base_url}/v1/processes/{process_id}/logs"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    closed_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    abort = False

    async def consume() -> None:
        """Consume the SSE stream."""
        try:
            async with transport.stream("GET", url, headers=headers, timeout=None) as response:
                if response.status_code >= 400:
                    raise SandboxAgentError(
                        f"Failed to follow process logs: {response.status_code}",
                        status_code=response.status_code,
                    )

                buffer = ""
                async for chunk in response.aiter_text():
                    if abort:
                        break

                    buffer += chunk.replace("\r\n", "\n")

                    while True:
                        separator = buffer.find("\n\n")
                        if separator == -1:
                            break

                        event_chunk = buffer[:separator]
                        buffer = buffer[separator + 2 :]

                        entry = _parse_log_sse_chunk(event_chunk)
                        if entry:
                            listener(entry)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            if not closed_future.done():
                closed_future.set_result(None)

    task = asyncio.create_task(consume())

    def close() -> None:
        nonlocal abort
        abort = True
        task.cancel()

    return ProcessLogSubscription(close, closed_future)


def _parse_log_sse_chunk(chunk: str) -> dict[str, Any] | None:
    """Parse a single SSE chunk into a process log entry.

    Args:
        chunk: The SSE chunk text.

    Returns:
        The parsed log entry dict, or None if not a log event.
    """
    if not chunk.strip():
        return None

    event_name = "message"
    data_lines: list[str] = []

    for line in chunk.split("\n"):
        if not line or line.startswith(":"):
            continue

        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue

        if line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if event_name != "log":
        return None

    data = "\n".join(data_lines)
    if not data.strip():
        return None

    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None

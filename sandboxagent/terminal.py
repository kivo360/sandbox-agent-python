"""Process terminal WebSocket support for interactive process I/O.

This module provides WebSocket-based terminal access to sandbox processes,
enabling interactive input/output with PTY support.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any

import websockets
from websockets.protocol import State

from sandboxagent.types import (
    ProcessTerminalExitFrame,
    ProcessTerminalInputFrame,
    ProcessTerminalReadyFrame,
    ProcessTerminalResizeFrame,
)

# WebSocket ready states (matching browser WebSocket API)
WS_READY_STATE_CONNECTING = 0
WS_READY_STATE_OPEN = 1
WS_READY_STATE_CLOSING = 2
WS_READY_STATE_CLOSED = 3


class ProcessTerminalSession:
    """WebSocket-based terminal session for interactive process I/O.

    This class provides an event-based API for interacting with a process
    terminal via WebSocket. It handles the frame protocol (JSON control
    frames + binary PTY data) and provides methods for sending input,
    resizing the terminal, and closing the connection.

    Example:
        >>> session = ProcessTerminalSession(websocket)
        >>> session.on_data(lambda data: print(data.decode()))
        >>> session.on_exit(lambda status: print(f"Exit code: {status.exit_code}"))
        >>> session.send_input("echo hello\n")
        >>> session.resize(cols=80, rows=24)
        >>> await session.close()
    """

    def __init__(self, websocket: websockets.WebSocketClientProtocol) -> None:
        """Initialize a new ProcessTerminalSession.

        Args:
            websocket: An established WebSocket connection to the terminal endpoint.
        """
        self._websocket = websocket
        self._closed = False
        self._close_signal_sent = False

        # Event listeners
        self._ready_listeners: set[Callable[[ProcessTerminalReadyFrame], None]] = set()
        self._data_listeners: set[Callable[[bytes], None]] = set()
        self._exit_listeners: set[Callable[[ProcessTerminalExitFrame], None]] = set()
        self._error_listeners: set[Callable[[Exception], None]] = set()
        self._close_listeners: set[Callable[[], None]] = set()

        # Start the message handler task
        self._handler_task: asyncio.Task[None] | None = None
        self._closed_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()

    @property
    def websocket(self) -> websockets.WebSocketClientProtocol:
        """The underlying WebSocket connection."""
        return self._websocket

    @property
    def closed(self) -> asyncio.Future[None]:
        """Future that resolves when the session is closed."""
        return self._closed_future

    def on_ready(self, listener: Callable[[ProcessTerminalReadyFrame], None]) -> Callable[[], None]:
        """Register a listener for terminal ready events.

        Args:
            listener: Callback function that receives the ready frame.

        Returns:
            A function that can be called to unregister the listener.
        """
        self._ready_listeners.add(listener)
        return lambda: self._ready_listeners.discard(listener)

    def on_data(self, listener: Callable[[bytes], None]) -> Callable[[], None]:
        """Register a listener for terminal data events.

        Args:
            listener: Callback function that receives binary terminal data (PTY output).

        Returns:
            A function that can be called to unregister the listener.
        """
        self._data_listeners.add(listener)
        return lambda: self._data_listeners.discard(listener)

    def on_exit(self, listener: Callable[[ProcessTerminalExitFrame], None]) -> Callable[[], None]:
        """Register a listener for terminal exit events.

        Args:
            listener: Callback function that receives the exit frame with exit code.

        Returns:
            A function that can be called to unregister the listener.
        """
        self._exit_listeners.add(listener)
        return lambda: self._exit_listeners.discard(listener)

    def on_error(self, listener: Callable[[Exception], None]) -> Callable[[], None]:
        """Register a listener for terminal error events.

        Args:
            listener: Callback function that receives error exceptions.

        Returns:
            A function that can be called to unregister the listener.
        """
        self._error_listeners.add(listener)
        return lambda: self._error_listeners.discard(listener)

    def on_close(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener for terminal close events.

        Args:
            listener: Callback function called when the terminal closes.

        Returns:
            A function that can be called to unregister the listener.
        """
        self._close_listeners.add(listener)
        return lambda: self._close_listeners.discard(listener)

    def send_input(self, data: str | bytes) -> None:
        """Send input to the terminal.

        Args:
            data: String or binary data to send to the terminal.
        """
        if self._websocket.state != State.OPEN:
            return

        # Encode the input data
        if isinstance(data, str):
            frame: ProcessTerminalInputFrame = {
                "type": "input",
                "data": data,
                "encoding": None,
            }
        else:
            # Binary data needs base64 encoding
            frame = {
                "type": "input",
                "data": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            }

        # Send as JSON control frame
        asyncio.create_task(self._send_json_frame(frame))

    def resize(self, cols: int, rows: int) -> None:
        """Resize the terminal.

        Args:
            cols: Number of columns.
            rows: Number of rows.
        """
        if self._websocket.state != State.OPEN:
            return

        frame: ProcessTerminalResizeFrame = {
            "type": "resize",
            "cols": cols,
            "rows": rows,
        }

        asyncio.create_task(self._send_json_frame(frame))

    async def close(self) -> None:
        """Close the terminal session gracefully."""
        if self._closed:
            return

        if self._websocket.state == State.CONNECTING:
            # Wait for connection to open, then close
            await self._websocket.wait_for_connection()
            await self.close()
            return

        if self._websocket.state == State.OPEN:
            if not self._close_signal_sent:
                self._close_signal_sent = True
                # Send close frame
                close_frame: dict[str, str] = {"type": "close"}
                try:
                    await self._websocket.send(json.dumps(close_frame))
                except Exception:
                    pass  # Best effort

            await self._websocket.close()

        self._closed = True

        # Resolve the closed future
        if not self._closed_future.done():
            self._closed_future.set_result(None)

        # Notify close listeners
        for listener in self._close_listeners:
            try:
                listener()
            except Exception:
                pass  # Don't let listener errors propagate

    async def _send_json_frame(self, frame: dict[str, Any]) -> None:
        """Send a JSON control frame to the WebSocket."""
        if self._websocket.state != State.OPEN:
            return

        try:
            await self._websocket.send(json.dumps(frame))
        except Exception as e:
            self._emit_error(e)

    async def start(self) -> None:
        """Start the message handler loop.

        This method starts listening for incoming messages from the WebSocket.
        It should be called after the WebSocket connection is established.
        """
        self._handler_task = asyncio.create_task(self._message_handler())

    async def _message_handler(self) -> None:
        """Handle incoming WebSocket messages."""
        try:
            async for message in self._websocket:
                await self._handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            # Connection closed normally
            pass
        except Exception as e:
            self._emit_error(e)
        finally:
            # Ensure closed future is resolved
            if not self._closed_future.done():
                self._closed_future.set_result(None)

            # Notify close listeners
            for listener in self._close_listeners:
                try:
                    listener()
                except Exception:
                    pass

    async def _handle_message(self, message: websockets.Data) -> None:
        """Handle a single WebSocket message.

        Args:
            message: The WebSocket message (text or binary).
        """
        try:
            if isinstance(message, str):
                # JSON control frame
                await self._handle_control_frame(message)
            else:
                # Binary data (PTY output)
                await self._handle_binary_data(message)
        except Exception as e:
            self._emit_error(e)

    async def _handle_control_frame(self, message: str) -> None:
        """Handle a JSON control frame from the server.

        Args:
            message: The JSON control frame as a string.
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self._emit_error(ValueError(f"Invalid JSON control frame: {message}"))
            return

        if not isinstance(data, dict) or "type" not in data:
            self._emit_error(ValueError(f"Invalid control frame structure: {data}"))
            return

        frame_type = data.get("type")

        if frame_type == "ready":
            # Terminal is ready - server sends camelCase
            ready_frame = ProcessTerminalReadyFrame(process_id=data.get("processId", ""))
            for listener in self._ready_listeners:
                try:
                    listener(ready_frame)
                except Exception:
                    pass

        elif frame_type == "exit":
            # Process exited - server sends camelCase
            exit_code = data.get("exitCode")
            exit_frame = ProcessTerminalExitFrame(exit_code=exit_code)
            for listener in self._exit_listeners:
                try:
                    listener(exit_frame)
                except Exception:
                    pass

        elif frame_type == "error":
            # Error from server
            message_text = data.get("message", "Unknown error")
            self._emit_error(RuntimeError(message_text))

        else:
            # Unknown frame type - treat as error
            self._emit_error(ValueError(f"Unknown control frame type: {frame_type}"))

    async def _handle_binary_data(self, data: bytes) -> None:
        """Handle binary data from the terminal (PTY output).

        Args:
            data: Binary data from the WebSocket.
        """
        for listener in self._data_listeners:
            try:
                listener(data)
            except Exception:
                pass

    def _emit_error(self, error: Exception) -> None:
        """Emit an error to all error listeners.

        Args:
            error: The exception to emit.
        """
        for listener in self._error_listeners:
            try:
                listener(error)
            except Exception:
                pass


async def connect_process_terminal(
    base_url: str,
    process_id: str,
    *,
    token: str | None = None,
) -> ProcessTerminalSession:
    """Connect to a process terminal WebSocket.

    Args:
        base_url: The base URL of the sandbox-agent server.
        process_id: The ID of the process to connect to.
        token: Optional authentication token.

    Returns:
        A connected ProcessTerminalSession instance.

    Raises:
        ConnectionError: If the WebSocket connection fails.
    """
    # Convert HTTP URL to WebSocket URL
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rstrip("/")

    # Build the terminal WebSocket URL
    path = f"/v1/processes/{process_id}/terminal/ws"
    url = f"{ws_url}{path}"

    # Add authentication if provided
    if token:
        url = f"{url}?access_token={token}"

    try:
        websocket = await websockets.connect(url)
    except Exception as e:
        raise ConnectionError(f"Failed to connect to terminal WebSocket: {e}") from e

    session = ProcessTerminalSession(websocket)
    await session.start()
    return session

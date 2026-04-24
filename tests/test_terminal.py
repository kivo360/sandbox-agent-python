"""Tests for process terminal WebSocket functionality."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sandboxagent.terminal import (
    ProcessTerminalSession,
    connect_process_terminal,
)
from sandboxagent.types import (
    ProcessTerminalExitFrame,
    ProcessTerminalReadyFrame,
)


class TestProcessTerminalSession:
    """Test ProcessTerminalSession functionality."""

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        """Create a mock WebSocket client protocol."""
        mock = AsyncMock()
        mock.state = MagicMock()
        mock.state.OPEN = 1
        mock.state.CONNECTING = 0
        mock.state.CLOSED = 3
        mock.state = 1  # OPEN
        return mock

    @pytest.fixture
    def terminal_session(self, mock_websocket: AsyncMock) -> ProcessTerminalSession:
        """Create a ProcessTerminalSession with a mock WebSocket."""
        return ProcessTerminalSession(mock_websocket)

    async def test_init(self, mock_websocket: AsyncMock) -> None:
        """Test session initialization."""
        session = ProcessTerminalSession(mock_websocket)
        assert session.websocket == mock_websocket
        assert not session._closed

    async def test_on_data_listener(self, terminal_session: ProcessTerminalSession) -> None:
        """Test registering and calling data listeners."""
        received_data: list[bytes] = []

        def on_data(data: bytes) -> None:
            received_data.append(data)

        # Register listener
        unregister = terminal_session.on_data(on_data)

        # Emit data
        test_data = b"hello world"
        for listener in terminal_session._data_listeners:
            listener(test_data)

        assert received_data == [test_data]

        # Unregister listener
        unregister()
        assert on_data not in terminal_session._data_listeners

    async def test_on_exit_listener(self, terminal_session: ProcessTerminalSession) -> None:
        """Test registering and calling exit listeners."""
        received_exits: list[ProcessTerminalExitFrame] = []

        def on_exit(frame: ProcessTerminalExitFrame) -> None:
            received_exits.append(frame)

        # Register listener
        unregister = terminal_session.on_exit(on_exit)

        # Emit exit
        exit_frame = ProcessTerminalExitFrame(exit_code=0)
        for listener in terminal_session._exit_listeners:
            listener(exit_frame)

        assert len(received_exits) == 1
        assert received_exits[0].exit_code == 0

        # Unregister listener
        unregister()
        assert on_exit not in terminal_session._exit_listeners

    async def test_on_error_listener(self, terminal_session: ProcessTerminalSession) -> None:
        """Test registering and calling error listeners."""
        received_errors: list[Exception] = []

        def on_error(error: Exception) -> None:
            received_errors.append(error)

        # Register listener
        unregister = terminal_session.on_error(on_error)

        # Emit error
        test_error = RuntimeError("test error")
        terminal_session._emit_error(test_error)

        assert received_errors == [test_error]

        # Unregister listener
        unregister()
        assert on_error not in terminal_session._error_listeners

    async def test_on_ready_listener(self, terminal_session: ProcessTerminalSession) -> None:
        """Test registering and calling ready listeners."""
        received_ready: list[ProcessTerminalReadyFrame] = []

        def on_ready(frame: ProcessTerminalReadyFrame) -> None:
            received_ready.append(frame)

        # Register listener
        unregister = terminal_session.on_ready(on_ready)

        # Emit ready
        ready_frame = ProcessTerminalReadyFrame(process_id="test-process")
        for listener in terminal_session._ready_listeners:
            listener(ready_frame)

        assert len(received_ready) == 1
        assert received_ready[0].process_id == "test-process"

        # Unregister listener
        unregister()
        assert on_ready not in terminal_session._ready_listeners

    async def test_on_close_listener(self, terminal_session: ProcessTerminalSession) -> None:
        """Test registering and calling close listeners."""
        close_called = False

        def on_close() -> None:
            nonlocal close_called
            close_called = True

        # Register listener
        unregister = terminal_session.on_close(on_close)

        # Emit close
        for listener in terminal_session._close_listeners:
            listener()

        assert close_called

        # Unregister listener
        unregister()
        assert on_close not in terminal_session._close_listeners

    async def test_send_input_string(self, terminal_session: ProcessTerminalSession, mock_websocket: AsyncMock) -> None:
        """Test sending string input."""
        terminal_session.send_input("hello\n")

        # Wait for async send
        await asyncio.sleep(0.01)

        # Check that send was called
        assert mock_websocket.send.called

    async def test_send_input_bytes(self, terminal_session: ProcessTerminalSession, mock_websocket: AsyncMock) -> None:
        """Test sending bytes input."""
        terminal_session.send_input(b"hello\n")

        # Wait for async send
        await asyncio.sleep(0.01)

        # Check that send was called
        assert mock_websocket.send.called

    async def test_resize(self, terminal_session: ProcessTerminalSession, mock_websocket: AsyncMock) -> None:
        """Test resizing the terminal."""
        terminal_session.resize(cols=80, rows=24)

        # Wait for async send
        await asyncio.sleep(0.01)

        # Check that send was called
        assert mock_websocket.send.called

    async def test_close(self, terminal_session: ProcessTerminalSession, mock_websocket: AsyncMock) -> None:
        """Test closing the session."""
        await terminal_session.close()

        assert terminal_session._closed
        assert mock_websocket.close.called

    async def test_handle_control_frame_ready(self, terminal_session: ProcessTerminalSession) -> None:
        """Test handling a ready control frame."""
        received_ready: list[ProcessTerminalReadyFrame] = []

        def on_ready(frame: ProcessTerminalReadyFrame) -> None:
            received_ready.append(frame)

        terminal_session.on_ready(on_ready)

        # Simulate ready frame
        await terminal_session._handle_control_frame(json.dumps({"type": "ready", "processId": "proc-123"}))

        assert len(received_ready) == 1
        assert received_ready[0].process_id == "proc-123"

    async def test_handle_control_frame_exit(self, terminal_session: ProcessTerminalSession) -> None:
        """Test handling an exit control frame."""
        received_exits: list[ProcessTerminalExitFrame] = []

        def on_exit(frame: ProcessTerminalExitFrame) -> None:
            received_exits.append(frame)

        terminal_session.on_exit(on_exit)

        # Simulate exit frame
        await terminal_session._handle_control_frame(json.dumps({"type": "exit", "exitCode": 42}))

        assert len(received_exits) == 1
        assert received_exits[0].exit_code == 42

    async def test_handle_control_frame_error(self, terminal_session: ProcessTerminalSession) -> None:
        """Test handling an error control frame."""
        received_errors: list[Exception] = []

        def on_error(error: Exception) -> None:
            received_errors.append(error)

        terminal_session.on_error(on_error)

        # Simulate error frame
        await terminal_session._handle_control_frame(json.dumps({"type": "error", "message": "Something went wrong"}))

        assert len(received_errors) == 1
        assert str(received_errors[0]) == "Something went wrong"

    async def test_handle_control_frame_invalid_json(self, terminal_session: ProcessTerminalSession) -> None:
        """Test handling invalid JSON control frame."""
        received_errors: list[Exception] = []

        def on_error(error: Exception) -> None:
            received_errors.append(error)

        terminal_session.on_error(on_error)

        # Simulate invalid JSON
        await terminal_session._handle_control_frame("not valid json")

        assert len(received_errors) == 1
        assert isinstance(received_errors[0], ValueError)

    async def test_handle_binary_data(self, terminal_session: ProcessTerminalSession) -> None:
        """Test handling binary data."""
        received_data: list[bytes] = []

        def on_data(data: bytes) -> None:
            received_data.append(data)

        terminal_session.on_data(on_data)

        # Simulate binary data
        test_data = b"binary terminal output"
        await terminal_session._handle_binary_data(test_data)

        assert received_data == [test_data]


class TestConnectProcessTerminal:
    """Test connect_process_terminal function."""

    @patch("sandboxagent.terminal.websockets.connect", new_callable=AsyncMock)
    async def test_connect_success(self, mock_connect: AsyncMock) -> None:
        """Test successful connection."""
        mock_websocket = AsyncMock()
        mock_connect.return_value = mock_websocket

        session = await connect_process_terminal(
            base_url="http://localhost:2468",
            process_id="proc-123",
        )

        assert isinstance(session, ProcessTerminalSession)
        mock_connect.assert_called_once()
        # Check URL is converted to ws://
        call_args = mock_connect.call_args[0][0]
        assert "ws://" in call_args
        assert "proc-123" in call_args

    @patch("sandboxagent.terminal.websockets.connect", new_callable=AsyncMock)
    async def test_connect_with_token(self, mock_connect: AsyncMock) -> None:
        """Test connection with authentication token."""
        mock_websocket = AsyncMock()
        mock_connect.return_value = mock_websocket

        await connect_process_terminal(
            base_url="http://localhost:2468",
            process_id="proc-123",
            token="secret-token",
        )

        # Check token is in URL
        call_args = mock_connect.call_args[0][0]
        assert "access_token=secret-token" in call_args

    @patch("sandboxagent.terminal.websockets.connect", new_callable=AsyncMock)
    async def test_connect_https_to_wss(self, mock_connect: AsyncMock) -> None:
        """Test that HTTPS URL is converted to WSS."""
        mock_websocket = AsyncMock()
        mock_connect.return_value = mock_websocket

        await connect_process_terminal(
            base_url="https://example.com",
            process_id="proc-123",
        )

        # Check URL uses wss://
        call_args = mock_connect.call_args[0][0]
        assert "wss://" in call_args

    @patch("sandboxagent.terminal.websockets.connect", new_callable=AsyncMock)
    async def test_connect_failure(self, mock_connect: AsyncMock) -> None:
        """Test connection failure raises ConnectionError."""
        mock_connect.side_effect = Exception("Connection refused")

        with pytest.raises(ConnectionError, match="Failed to connect to terminal WebSocket"):
            await connect_process_terminal(
                base_url="http://localhost:2468",
                process_id="proc-123",
            )

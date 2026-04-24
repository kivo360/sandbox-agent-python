"""Tests for desktop streaming functionality."""

from __future__ import annotations

import platform
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sandboxagent import DesktopNotSupportedError, DesktopStreamSession, Session
from sandboxagent.client import SandboxAgent
from sandboxagent.http import SandboxAgentError

# Skip all desktop tests on macOS (desktop APIs return 501 on macOS)
pytestmark = [
    pytest.mark.skipif(
        platform.system() == "Darwin",
        reason="Desktop streaming not supported on macOS (server returns 501)",
    ),
    pytest.mark.asyncio,
]


class TestDesktopNotSupportedError:
    """Tests for DesktopNotSupportedError exception."""

    def test_default_message(self) -> None:
        """Test that default message is provided."""
        error = DesktopNotSupportedError()
        assert "not supported on this platform" in error.message
        assert "Only Linux" in error.message
        assert str(error) == error.message

    def test_custom_message(self) -> None:
        """Test that custom message can be provided."""
        custom = "Custom error message"
        error = DesktopNotSupportedError(custom)
        assert error.message == custom
        assert str(error) == custom


class TestDesktopStreamSession:
    """Tests for DesktopStreamSession class."""

    async def test_initialization(self) -> None:
        """Test that DesktopStreamSession can be initialized."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        assert session._websocket == mock_ws
        assert session._pc is None
        assert session._data_channel is None
        assert session._media_stream is None
        assert not session._connected
        assert session._closed is False

    async def test_on_ready_listener(self) -> None:
        """Test on_ready listener registration and callback."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        called_with = None

        def listener(status):
            nonlocal called_with
            called_with = status

        # Register listener
        session.on_ready(listener)
        assert listener in session._ready_listeners

        # Simulate ready status
        from sandboxagent.desktop import DesktopStreamReadyStatus

        status = DesktopStreamReadyStatus(type="ready", width=1920, height=1080)
        session._cached_ready_status = status

        # Call listeners
        for lst in session._ready_listeners:
            lst(status)

        assert called_with is not None
        assert called_with.width == 1920
        assert called_with.height == 1080

    async def test_on_ready_late_listener_gets_cached_status(self) -> None:
        """Test that late listeners receive cached ready status."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Set cached status first
        from sandboxagent.desktop import DesktopStreamReadyStatus

        status = DesktopStreamReadyStatus(type="ready", width=1920, height=1080)
        session._cached_ready_status = status

        # Register listener after status is cached
        called_with = None

        def listener(s):
            nonlocal called_with
            called_with = s

        session.on_ready(listener)

        # Listener should be called immediately with cached status
        assert called_with is not None
        assert called_with.width == 1920

    async def test_on_track_listener(self) -> None:
        """Test on_track listener registration."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        called = False

        def listener(track):
            nonlocal called
            called = True

        session.on_track(listener)
        assert listener in session._track_listeners

    async def test_on_connect_listener(self) -> None:
        """Test on_connect listener registration."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        called = False

        def listener():
            nonlocal called
            called = True

        session.on_connect(listener)
        assert listener in session._connect_listeners

    async def test_on_disconnect_listener(self) -> None:
        """Test on_disconnect listener registration."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        called = False

        def listener():
            nonlocal called
            called = True

        session.on_disconnect(listener)
        assert listener in session._disconnect_listeners

    async def test_on_error_listener(self) -> None:
        """Test on_error listener registration."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        called_with = None

        def listener(error):
            nonlocal called_with
            called_with = error

        session.on_error(listener)
        assert listener in session._error_listeners

        # Emit error
        error = Exception("Test error")
        session._emit_error(error)

        assert called_with == error

    async def test_get_media_stream(self) -> None:
        """Test get_media_stream returns current stream."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        assert session.get_media_stream() is None

        # Set a mock stream
        mock_stream = MagicMock()
        session._media_stream = mock_stream

        assert session.get_media_stream() == mock_stream

    async def test_close(self) -> None:
        """Test close method."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        session = DesktopStreamSession(mock_ws)

        # Close should not raise
        session.close()

        assert session._closed is True

    async def test_close_idempotent(self) -> None:
        """Test that close is idempotent."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        session.close()
        session.close()  # Should not raise

        assert session._closed is True


class TestNekoProtocol:
    """Tests for Neko binary protocol implementation."""

    async def test_mouse_button_to_x11(self) -> None:
        """Test mouse button mapping."""
        from sandboxagent.desktop import _mouse_button_to_x11

        assert _mouse_button_to_x11("left") == 1
        assert _mouse_button_to_x11(None) == 1
        assert _mouse_button_to_x11("middle") == 2
        assert _mouse_button_to_x11("right") == 3
        assert _mouse_button_to_x11("unknown") == 1

    async def test_key_to_x11_keysym_ascii(self) -> None:
        """Test ASCII key mapping."""
        from sandboxagent.desktop import _key_to_x11_keysym

        # ASCII characters
        assert _key_to_x11_keysym("a") == ord("a")
        assert _key_to_x11_keysym("A") == ord("A")
        assert _key_to_x11_keysym("1") == ord("1")

    async def test_key_to_x11_keysym_special(self) -> None:
        """Test special key mapping."""
        from sandboxagent.desktop import _key_to_x11_keysym

        # Special keys
        assert _key_to_x11_keysym("Enter") == 0xFF0D
        assert _key_to_x11_keysym("Escape") == 0xFF1B
        assert _key_to_x11_keysym("Space") == 0x0020
        assert _key_to_x11_keysym("ArrowLeft") == 0xFF51
        assert _key_to_x11_keysym("F1") == 0xFFBE

    async def test_key_to_x11_keysym_unknown(self) -> None:
        """Test unknown key returns 0."""
        from sandboxagent.desktop import _key_to_x11_keysym

        assert _key_to_x11_keysym("UnknownKey123") == 0


class TestSessionStartDesktop:
    """Tests for Session.start_desktop() method."""

    async def test_start_desktop_raises_on_501(self) -> None:
        """Test that 501 error raises DesktopNotSupportedError."""
        # Create mock sandbox
        mock_sandbox = MagicMock(spec=SandboxAgent)

        # Create a mock response for 501 error
        mock_response = MagicMock()
        mock_response.status_code = 501
        mock_response.text = "Not Implemented"

        # Make desktop_stream_start raise SandboxAgentError with 501
        error = SandboxAgentError(
            status=501,
            problem={"title": "Not Implemented", "detail": "Desktop not available"},
            response=mock_response,
        )
        mock_sandbox.desktop_stream_start = AsyncMock(side_effect=error)

        # Create mock session record
        mock_record = MagicMock()
        mock_record.id = "test-session"
        mock_record.agent_session_id = "agent-123"

        # Create session
        session = Session(mock_sandbox, mock_record)

        # Should raise DesktopNotSupportedError
        with pytest.raises(DesktopNotSupportedError) as exc_info:
            await session.start_desktop()

        assert "not supported on this platform" in str(exc_info.value)
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, SandboxAgentError)

    async def test_start_desktop_raises_on_other_error(self) -> None:
        """Test that other errors are re-raised."""
        # Create mock sandbox
        mock_sandbox = MagicMock(spec=SandboxAgent)

        # Make desktop_stream_start raise a different error
        mock_response = MagicMock()
        mock_response.status_code = 500

        error = SandboxAgentError(
            status=500,
            problem={"title": "Internal Server Error"},
            response=mock_response,
        )
        mock_sandbox.desktop_stream_start = AsyncMock(side_effect=error)

        # Create mock session record
        mock_record = MagicMock()
        mock_record.id = "test-session"
        mock_record.agent_session_id = "agent-123"

        # Create session
        session = Session(mock_sandbox, mock_record)

        # Should re-raise the original error
        with pytest.raises(SandboxAgentError) as exc_info:
            await session.start_desktop()

        assert exc_info.value.status == 500

    async def test_start_desktop_success(self) -> None:
        """Test successful desktop stream start."""
        # Create mock sandbox
        mock_sandbox = MagicMock(spec=SandboxAgent)
        mock_sandbox.desktop_stream_start = AsyncMock(return_value={
            "websocketUrl": "ws://localhost:8080/desktop",
            "sessionId": "desktop-123",
        })

        # Create mock session record
        mock_record = MagicMock()
        mock_record.id = "test-session"
        mock_record.agent_session_id = "agent-123"

        # Create session
        session = Session(mock_sandbox, mock_record)

        # Mock websockets.connect
        mock_ws = AsyncMock()

        with patch("websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            with patch.object(DesktopStreamSession, "start", new_callable=AsyncMock):
                desktop_session = await session.start_desktop()

        assert isinstance(desktop_session, DesktopStreamSession)
        mock_sandbox.desktop_stream_start.assert_called_once()

    async def test_start_desktop_with_dimensions(self) -> None:
        """Test desktop stream start with width and height."""
        # Create mock sandbox
        mock_sandbox = MagicMock(spec=SandboxAgent)
        mock_sandbox.desktop_stream_start = AsyncMock(return_value={
            "websocketUrl": "ws://localhost:8080/desktop",
            "sessionId": "desktop-123",
        })

        # Create mock session record
        mock_record = MagicMock()
        mock_record.id = "test-session"
        mock_record.agent_session_id = "agent-123"

        # Create session
        session = Session(mock_sandbox, mock_record)

        # Mock websockets.connect
        mock_ws = AsyncMock()

        with patch("websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            with patch.object(DesktopStreamSession, "start", new_callable=AsyncMock):
                await session.start_desktop(width=1920, height=1080)

        # Verify the request included dimensions
        mock_sandbox.desktop_stream_start.assert_called_once_with(
            width=1920,
            height=1080,
        )

    async def test_start_desktop_missing_websocket_url(self) -> None:
        """Test error when websocket URL is missing."""
        # Create mock sandbox
        mock_sandbox = MagicMock(spec=SandboxAgent)
        mock_sandbox.desktop_stream_start = AsyncMock(return_value={
            "sessionId": "desktop-123",
            # No websocketUrl
        })

        # Create mock session record
        mock_record = MagicMock()
        mock_record.id = "test-session"
        mock_record.agent_session_id = "agent-123"

        # Create session
        session = Session(mock_sandbox, mock_record)

        # Should raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            await session.start_desktop()

        assert "No WebSocket URL" in str(exc_info.value)


class TestDesktopStreamSessionInputMethods:
    """Tests for DesktopStreamSession input methods."""

    async def test_move_mouse(self) -> None:
        """Test move_mouse sends correct message."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Mock data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "open"
        session._data_channel = mock_channel

        session.move_mouse(100, 200)

        # Verify data was sent
        assert mock_channel.send.called

    async def test_mouse_click(self) -> None:
        """Test mouse_click sends correct messages."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Mock data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "open"
        session._data_channel = mock_channel

        session.mouse_click("left", 100, 200)

        # Should send multiple messages (move, down, up)
        assert mock_channel.send.call_count == 3

    async def test_key_press(self) -> None:
        """Test key_press sends correct messages."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Mock data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "open"
        session._data_channel = mock_channel

        session.key_press("Enter")

        # Should send down and up
        assert mock_channel.send.call_count == 2

    async def test_type_text(self) -> None:
        """Test type_text sends correct messages."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Mock data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "open"
        session._data_channel = mock_channel

        session.type_text("hi")

        # Should send 4 messages (h down, h up, i down, i up)
        assert mock_channel.send.call_count == 4

    async def test_scroll(self) -> None:
        """Test scroll sends correct message."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Mock data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "open"
        session._data_channel = mock_channel

        session.scroll(100, 200, delta_x=0, delta_y=-3)

        # Should send move and scroll
        assert mock_channel.send.call_count == 2

    async def test_input_without_data_channel(self) -> None:
        """Test that input methods don't fail when data channel is not ready."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # No data channel set
        session._data_channel = None

        # Should not raise
        session.move_mouse(100, 200)
        session.mouse_click("left")
        session.key_press("Enter")

    async def test_input_with_closed_data_channel(self) -> None:
        """Test that input methods don't fail when data channel is closed."""
        mock_ws = MagicMock()
        session = DesktopStreamSession(mock_ws)

        # Closed data channel
        mock_channel = MagicMock()
        mock_channel.readyState = "closed"
        session._data_channel = mock_channel

        # Should not raise
        session.move_mouse(100, 200)
        session.mouse_click("left")
        session.key_press("Enter")

        # Should not send anything
        assert not mock_channel.send.called

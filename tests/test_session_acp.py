"""Unit tests for Session ACP integration."""

from __future__ import annotations

from typing import Any
import asyncio
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx
from respx import MockRouter

from sandboxagent import (
    AcpHttpClient,
    PermissionRequest,
    PermissionResponse,
    SandboxAgent,
    Session,
)
from sandboxagent.types import SessionRecord

BASE_URL = "http://localhost:2468"


@pytest.fixture
def respx_mock() -> MockRouter:
    with respx.mock(base_url=BASE_URL, assert_all_mocked=False) as router:
        yield router


@pytest.fixture
def session_record() -> SessionRecord:
    return SessionRecord(
        id="test-session-id",
        agent="test-agent",
        agent_session_id="agent-session-123",
        last_connection_id="conn-123",
        created_at=1234567890,
    )


class TestSessionAcpIntegration:
    """Test Session integration with AcpHttpClient."""

    async def test_session_acp_client_property(self, session_record: SessionRecord) -> None:
        """Test that Session exposes the acp_client property."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        assert session.acp_client is mock_acp

    async def test_session_without_acp_client(self, session_record: SessionRecord) -> None:
        """Test that Session works without an ACP client (backward compatibility)."""
        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=None,
        )

        assert session.acp_client is None
        assert session.id == "test-session-id"
        assert session.agent == "test-agent"
        assert session.agent_session_id == "agent-session-123"

    async def test_session_prompt_delegates_to_acp(self, session_record: SessionRecord) -> None:
        """Test that Session.prompt() delegates to acp.prompt()."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.prompt = AsyncMock(return_value={"content": "Hello!"})

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        response = await session.prompt("Hello!")

        mock_acp.prompt.assert_called_once()
        call_args = mock_acp.prompt.call_args[0][0]
        assert call_args["sessionId"] == "agent-session-123"
        assert call_args["prompt"] == "Hello!"
        assert call_args["streaming"] is False
        assert response["content"] == "Hello!"

    async def test_session_prompt_with_attachments(self, session_record: SessionRecord) -> None:
        """Test Session.prompt() with attachments."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.prompt = AsyncMock(return_value={"content": "File received"})

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        attachments = [{"name": "test.txt", "content": "Hello"}]
        await session.prompt("Check this file", attachments=attachments, streaming=True)

        call_args = mock_acp.prompt.call_args[0][0]
        assert call_args["attachments"] == attachments
        assert call_args["streaming"] is True

    async def test_session_prompt_without_acp_raises(self, session_record: SessionRecord) -> None:
        """Test that Session.prompt() raises when no ACP client is set."""
        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=None,
        )

        with pytest.raises(RuntimeError, match="Session is not connected to an ACP client"):
            await session.prompt("Hello!")

    async def test_session_on_message_handler(self, session_record: SessionRecord) -> None:
        """Test Session.on_message() registers handler on ACP client."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.on_message = None

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        @session.on_message
        def handler(msg: dict[str, Any]) -> None:
            pass

        assert mock_acp.on_message is handler

    async def test_session_on_error_handler(self, session_record: SessionRecord) -> None:
        """Test Session.on_error() registers handler on ACP client."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.on_error = None

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        @session.on_error
        def handler(error: Exception) -> None:
            pass

        assert mock_acp.on_error is handler

    async def test_session_on_close_handler(self, session_record: SessionRecord) -> None:
        """Test Session.on_close() registers handler on ACP client."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.on_close = None

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        @session.on_close
        def handler() -> None:
            pass

        assert mock_acp.on_close is handler

    async def test_session_set_permission_callback(self, session_record: SessionRecord) -> None:
        """Test Session.set_permission_callback() sets callback on ACP client."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.on_permission_request = None

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        def callback(request: PermissionRequest) -> PermissionResponse:
            return PermissionResponse(id=request["id"], outcome={"outcome": "allowed"})

        session.set_permission_callback(callback)

        assert session._permission_callback is callback
        assert mock_acp.on_permission_request is callback

    async def test_session_set_permission_callback_none(self, session_record: SessionRecord) -> None:
        """Test Session.set_permission_callback() with None for auto-deny."""
        mock_acp = MagicMock(spec=AcpHttpClient)

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        session.set_permission_callback(None)

        assert session._permission_callback is None
        assert mock_acp.on_permission_request is None

    async def test_session_initialize(self, session_record: SessionRecord) -> None:
        """Test Session.initialize() connects and initializes ACP."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.connect = AsyncMock()
        mock_acp.initialize = AsyncMock(return_value={
            "protocolVersion": "2025-03-18",
            "capabilities": {},
            "serverInfo": {"name": "test", "version": "1.0"},
        })

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        response = await session.initialize()

        mock_acp.connect.assert_called_once()
        mock_acp.initialize.assert_called_once()
        assert response["protocolVersion"] == "2025-03-18"

    async def test_session_authenticate(self, session_record: SessionRecord) -> None:
        """Test Session.authenticate() delegates to ACP."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.authenticate = AsyncMock(return_value={"success": True})

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        response = await session.authenticate("my-token")

        mock_acp.authenticate.assert_called_once_with({"token": "my-token"})
        assert response["success"] is True

    async def test_session_new_session(self, session_record: SessionRecord) -> None:
        """Test Session.new_session() creates a new session via ACP."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.new_session = AsyncMock(return_value={
            "sessionId": "new-session-123",
            "agentSessionId": "agent-new-123",
        })

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        response = await session.new_session(
            agent="claude",
            session_init={"cwd": "/tmp"},
            config_options=[{"id": "model", "value": "gpt-4"}],
        )

        mock_acp.new_session.assert_called_once()
        call_args = mock_acp.new_session.call_args[0][0]
        assert call_args["agent"] == "claude"
        assert call_args["sessionInit"] == {"cwd": "/tmp"}
        assert call_args["configOptions"] == [{"id": "model", "value": "gpt-4"}]
        assert response["sessionId"] == "new-session-123"

    async def test_session_load_session(self, session_record: SessionRecord) -> None:
        """Test Session.load_session() loads an existing session via ACP."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.load_session = AsyncMock(return_value={
            "sessionId": "loaded-session-123",
            "agentSessionId": "agent-loaded-123",
        })

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        response = await session.load_session("session-to-load")

        mock_acp.load_session.assert_called_once_with({"sessionId": "session-to-load"})
        assert response["sessionId"] == "loaded-session-123"

    async def test_session_cancel(self, session_record: SessionRecord) -> None:
        """Test Session.cancel() sends cancel notification via ACP."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        mock_acp.cancel = AsyncMock()

        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        await session.cancel("request-123")

        mock_acp.cancel.assert_called_once_with({
            "sessionId": "agent-session-123",
            "requestId": "request-123",
        })

    async def test_session_to_record(self, session_record: SessionRecord) -> None:
        """Test Session.to_record() returns a copy of the record."""
        mock_acp = MagicMock(spec=AcpHttpClient)
        session = Session(
            sandbox=MagicMock(),
            record=session_record,
            acp_client=mock_acp,
        )

        record = session.to_record()

        assert record.id == "test-session-id"
        assert record.agent == "test-agent"
        # Should be a copy, not the same object
        assert record is not session._record


class TestSandboxAgentCreateSession:
    """Test SandboxAgent.create_session() method."""

    async def test_create_session_returns_wired_session(self, respx_mock: MockRouter) -> None:
        """Test that create_session returns a Session wired to AcpHttpClient."""
        # Mock the ACP SSE connection (returns 200 with stream)
        respx_mock.get("/v1/acp/test-server").respond(200, text="data: {}\n\n")

        # Mock the ACP POST endpoints
        respx_mock.post("/v1/acp/test-server").mock(side_effect=[
            # initialize response
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "protocolVersion": "2025-03-18",
                    "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1.0"},
                },
            }),
            # new_session response
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "2",
                "result": {
                    "sessionId": "new-session-123",
                    "agentSessionId": "agent-session-456",
                },
            }),
        ])

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        # Create session
        session = await agent.create_session(
            agent="claude",
            server_id="test-server",
)

        # Verify session is properly wired
        assert isinstance(session, Session)
        assert session.agent == "claude"
        assert session.acp_client is not None
        assert isinstance(session.acp_client, AcpHttpClient)

        await asyncio.sleep(0.1)  # Let SSE task start
        await agent.dispose()

    async def test_create_session_with_callbacks(self, respx_mock: MockRouter) -> None:
        """Test create_session with event handlers."""
        respx_mock.get("/v1/acp/test-server").respond(200, text="data: {}\n\n")
        respx_mock.post("/v1/acp/test-server").mock(side_effect=[
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "protocolVersion": "2025-03-18",
                    "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1.0"},
                },
            }),
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "2",
                "result": {
                    "sessionId": "session-123",
                    "agentSessionId": "agent-456",
                },
            }),
        ])

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        messages: list[dict[str, Any]] = []
        errors: list[Exception] = []
        close_called = False

        def on_message(msg: dict[str, Any]) -> None:
            messages.append(msg)

        def on_error(error: Exception) -> None:
            errors.append(error)

        def on_close() -> None:
            nonlocal close_called
            close_called = True

        session = await agent.create_session(
            agent="claude",
            server_id="test-server",
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        # Verify callbacks are registered
        assert session.acp_client.on_message is not None
        assert session.acp_client.on_error is on_error
        assert session.acp_client.on_close is on_close

        await asyncio.sleep(0.1)  # Let SSE task start
        await agent.dispose()

    async def test_create_session_with_permission_callback(self, respx_mock: MockRouter) -> None:
        """Test create_session with permission handler."""
        respx_mock.get("/v1/acp/test-server").respond(200, text="data: {}\n\n")
        respx_mock.post("/v1/acp/test-server").mock(side_effect=[
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "protocolVersion": "2025-03-18",
                    "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1.0"},
                },
            }),
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "2",
                "result": {
                    "sessionId": "session-123",
                    "agentSessionId": "agent-456",
                },
            }),
        ])

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        def on_permission(request: PermissionRequest) -> PermissionResponse:
            return PermissionResponse(id=request["id"], outcome={"outcome": "allowed"})

        session = await agent.create_session(
            agent="claude",
            server_id="test-server",
            on_permission_request=on_permission,
        )

        # Verify permission callback is registered
        assert session.acp_client.on_permission_request is on_permission

        await asyncio.sleep(0.1)  # Let SSE task start
        await agent.dispose()

    async def test_create_session_with_custom_session_id(self, respx_mock: MockRouter) -> None:
        """Test create_session with explicit session ID."""
        respx_mock.get("/v1/acp/test-server").respond(200, text="data: {}\n\n")
        respx_mock.post("/v1/acp/test-server").mock(side_effect=[
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {
                    "protocolVersion": "2025-03-18",
                    "capabilities": {},
                    "serverInfo": {"name": "test", "version": "1.0"},
                },
            }),
            respx.MockResponse(200, json={
                "jsonrpc": "2.0",
                "id": "2",
                "result": {
                    "sessionId": "server-session-123",
                    "agentSessionId": "agent-456",
                },
            }),
        ])

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        session = await agent.create_session(
            agent="claude",
            server_id="test-server",
            session_id="my-custom-session-id",
        )

        # Verify the session uses the custom ID
        assert session.id == "my-custom-session-id"

        await asyncio.sleep(0.1)  # Let SSE task start
        await agent.dispose()

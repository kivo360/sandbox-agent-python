"""Live ACP connection management for session observation and event persistence.

This module provides the LiveAcpConnection class that manages ACP connections
with envelope observation, permission request queuing, session binding, and replay
capabilities. Ported from the TypeScript SDK.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any, TypedDict

from sandboxagent.acp import (
    AcpHttpClient,
    CancelNotification,
    NewSessionRequest,
    NewSessionResponse,
    PermissionRequest,
    PermissionResponse,
    PromptRequest,
    SetSessionConfigOptionRequest,
    SetSessionModeRequest,
)
from sandboxagent.types import SessionEvent

logger = logging.getLogger(__name__)

# Constants
PROTOCOL_VERSION = "2025-03-18"
API_PREFIX = "/v1"
MAX_EVENT_INDEX_INSERT_RETRIES = 3
DEFAULT_REPLAY_MAX_CHARS = 100_000


class AcpEnvelopeDirection:
    """Direction of ACP envelope flow."""

    OUTBOUND = "outbound"
    INBOUND = "inbound"


class RequestPermissionRequest(TypedDict, total=False):
    """Permission request from the agent."""

    id: str
    sessionId: str
    options: list[dict[str, Any]]
    toolCall: dict[str, Any] | None


class RequestPermissionResponse(TypedDict, total=False):
    """Response to a permission request."""

    outcome: dict[str, Any]


class SessionSendOptions(TypedDict, total=False):
    """Options for sending session methods."""

    notification: bool


def _random_id() -> str:
    """Generate a random ID."""
    return str(uuid.uuid4())


def _now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(asyncio.get_event_loop().time() * 1000)


def _clone_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Deep clone an envelope."""
    return copy.deepcopy(envelope)


def _clone_permission_request(request: RequestPermissionRequest) -> RequestPermissionRequest:
    """Deep clone a permission request."""
    return copy.deepcopy(request)


def _cancelled_permission_response() -> RequestPermissionResponse:
    """Create a cancelled permission response."""
    return {"outcome": {"outcome": "cancelled"}}


def _envelope_id(envelope: dict[str, Any]) -> str | None:
    """Extract the ID from an envelope."""
    msg_id = envelope.get("id")
    if msg_id is None:
        return None
    return str(msg_id)


def _envelope_method(envelope: dict[str, Any]) -> str | None:
    """Extract the method from an envelope."""
    method = envelope.get("method")
    if isinstance(method, str):
        return method
    return None


def _envelope_session_id_from_params(envelope: dict[str, Any]) -> str | None:
    """Extract session ID from envelope params."""
    params = envelope.get("params")
    if not isinstance(params, dict):
        return None
    session_id = params.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _envelope_session_id_from_result(envelope: dict[str, Any]) -> str | None:
    """Extract session ID from envelope result."""
    result = envelope.get("result")
    if not isinstance(result, dict):
        return None
    session_id = result.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


def _inject_replay_prompt(params: dict[str, Any], replay_text: str) -> None:
    """Inject replay text into prompt params."""
    prompt = params.get("prompt", "")
    if isinstance(prompt, str):
        prompt = f"{replay_text}\n\n{prompt}"
    else:
        prompt = replay_text
    params["prompt"] = prompt


def _build_replay_text(events: list[SessionEvent], max_chars: int = DEFAULT_REPLAY_MAX_CHARS) -> str | None:
    """Build replay text from session events.

    Args:
        events: List of session events to include in replay.
        max_chars: Maximum characters for the replay text.

    Returns:
        Replay text string or None if no events.
    """
    if not events:
        return None

    prefix = "Previous session history is replayed below as JSON-RPC envelopes. Use it as context before responding to the latest user prompt.\n"
    text = prefix

    for event in events:
        line = json.dumps({
            "createdAt": event.created_at,
            "sender": event.sender,
            "payload": event.payload,
        })

        if len(text) + len(line) + 1 > max_chars:
            text += "\n[history truncated]"
            break

        text += f"{line}\n"

    return text


class LiveAcpConnection:
    """Manages a live ACP connection with envelope observation and session binding.

    This class handles:
    - ACP connection per server_id
    - Envelope observation: watches all incoming/outgoing envelopes
    - Permission request queuing: queues permission requests until handler responds
    - Session binding: binds sessions to connections with ID mapping
    - Replay support: stores events for session replay
    """

    def __init__(
        self,
        agent: str,
        connection_id: str,
        acp: AcpHttpClient,
        on_observed_envelope: Callable[[LiveAcpConnection, dict[str, Any], str, str | None], None],
        on_permission_request: Callable[[LiveAcpConnection, str, str, RequestPermissionRequest], asyncio.Future[RequestPermissionResponse]],
    ) -> None:
        """Initialize the live ACP connection.

        Args:
            agent: The agent identifier.
            connection_id: Unique connection identifier.
            acp: The ACP HTTP client.
            on_observed_envelope: Callback for observed envelopes.
            on_permission_request: Callback for permission requests.
        """
        self.agent = agent
        self.connection_id = connection_id
        self._acp = acp
        self._on_observed_envelope = on_observed_envelope
        self._on_permission_request = on_permission_request

        # Session ID mappings
        self._session_by_local_id: dict[str, str] = {}
        self._local_by_agent_session_id: dict[str, str] = {}

        # Pending state
        self._pending_new_session_locals: list[str] = []
        self._pending_request_session_by_id: dict[str, str] = {}
        self._pending_replay_by_local_session_id: dict[str, str] = {}

        # Adapter exit tracking
        self._last_adapter_exit: dict[str, Any] | None = None
        self._last_adapter_exit_at = 0

        # Locks for thread safety
        self._lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        base_url: str,
        agent: str,
        server_id: str,
        on_observed_envelope: Callable[[LiveAcpConnection, dict[str, Any], str, str | None], None],
        on_permission_request: Callable[[LiveAcpConnection, str, str, RequestPermissionRequest], asyncio.Future[RequestPermissionResponse]],
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> LiveAcpConnection:
        """Create and initialize a new LiveAcpConnection.

        Args:
            base_url: Base URL of the sandbox-agent server.
            agent: The agent identifier.
            server_id: ID of the ACP server instance.
            on_observed_envelope: Callback for observed envelopes.
            on_permission_request: Callback for permission requests.
            token: Optional bearer token for authentication.
            headers: Optional additional HTTP headers.

        Returns:
            Initialized LiveAcpConnection instance.
        """
        connection_id = _random_id()

        # Create placeholder for live reference (set after construction)
        live_ref: list[LiveAcpConnection | None] = [None]

        async def permission_handler(request: PermissionRequest) -> PermissionResponse:
            """Handle permission requests from ACP."""
            live = live_ref[0]
            if live is None:
                return _cancelled_permission_response()

            # Convert to RequestPermissionRequest format
            req: RequestPermissionRequest = {
                "id": request.get("id", ""),
                "sessionId": request.get("sessionId", ""),
                "options": request.get("permission", {}).get("options", []),
                "toolCall": request.get("permission", {}).get("toolCall"),
            }

            return await live._handle_permission_request(req)

        def envelope_handler(envelope: dict[str, Any], direction: str) -> None:
            """Handle envelopes from ACP."""
            live = live_ref[0]
            if live is None:
                return
            live._handle_envelope(envelope, direction)

        # Create ACP client with callbacks
        acp = AcpHttpClient(
            base_url=base_url,
            server_id=server_id,
            token=token,
            headers=headers,
            on_permission_request=permission_handler,
        )

        # Create the live connection instance
        live = cls(
            agent=agent,
            connection_id=connection_id,
            acp=acp,
            on_observed_envelope=on_observed_envelope,
            on_permission_request=on_permission_request,
        )

        # Set the reference for callbacks
        live_ref[0] = live

        # Connect and initialize
        await acp.connect()

        # Initialize the connection
        init_result = await acp.initialize({
            "protocolVersion": PROTOCOL_VERSION,
            "clientInfo": {
                "name": "sandboxagent-python",
                "version": "0.1.5",
            },
        })

        # Handle authentication if required
        auth_methods = init_result.get("authMethods", [])
        if auth_methods:
            await cls._auto_authenticate(acp, auth_methods)

        return live

    @staticmethod
    async def _auto_authenticate(acp: AcpHttpClient, methods: list[dict[str, Any]]) -> None:
        """Auto-authenticate based on advertised auth methods."""
        # Prefer env-var-based methods
        env_based = None
        for method in methods:
            method_id = method.get("id", "")
            if method_id in ("codex-api-key", "openai-api-key", "anthropic-api-key"):
                env_based = method
                break

        if not env_based:
            return

        try:
            await acp.authenticate({"token": ""})  # Token from env var on server side
        except Exception:
            # Authentication is best-effort
            pass

    async def disconnect(self) -> None:
        """Disconnect from the ACP server."""
        await self._acp.disconnect()

    def has_bound_session(self, local_session_id: str, agent_session_id: str | None = None) -> bool:
        """Check if a local session is bound to this connection.

        Args:
            local_session_id: The local session ID.
            agent_session_id: Optional agent session ID to verify.

        Returns:
            True if the session is bound (and optionally matches agent_session_id).
        """
        bound = self._session_by_local_id.get(local_session_id)
        if not bound:
            return False
        if agent_session_id and bound != agent_session_id:
            return False
        return True

    def bind_session(self, local_session_id: str, agent_session_id: str) -> None:
        """Bind a local session to an agent session ID.

        Args:
            local_session_id: The local session ID.
            agent_session_id: The agent session ID.
        """
        self._session_by_local_id[local_session_id] = agent_session_id
        self._local_by_agent_session_id[agent_session_id] = local_session_id

    def queue_replay(self, local_session_id: str, replay_text: str | None) -> None:
        """Queue replay text for a session.

        Args:
            local_session_id: The local session ID.
            replay_text: Replay text to inject on next prompt, or None to clear.
        """
        if replay_text is None:
            self._pending_replay_by_local_session_id.pop(local_session_id, None)
        else:
            self._pending_replay_by_local_session_id[local_session_id] = replay_text

    async def create_remote_session(
        self,
        local_session_id: str,
        session_init: NewSessionRequest,
    ) -> NewSessionResponse:
        """Create a remote session and bind it to the local session.

        Args:
            local_session_id: The local session ID to bind.
            session_init: Session initialization parameters.

        Returns:
            NewSessionResponse from the agent.

        Raises:
            Error if the agent process exits during session creation.
        """
        create_started_at = _now_ms()
        self._pending_new_session_locals.append(local_session_id)

        try:
            response = await self._acp.new_session(session_init)
            agent_session_id = response.get("agentSessionId")
            if agent_session_id:
                self.bind_session(local_session_id, agent_session_id)
            return response
        except Exception as error:
            # Remove from pending
            if local_session_id in self._pending_new_session_locals:
                self._pending_new_session_locals.remove(local_session_id)

            # Check if adapter exited during creation
            adapter_exit = self._last_adapter_exit
            if adapter_exit and self._last_adapter_exit_at >= create_started_at:
                code = adapter_exit.get("code")
                suffix = f" (code {code})" if code is not None else ""
                raise RuntimeError(f"Agent process exited while creating session{suffix}") from error

            raise

    async def send_session_method(
        self,
        local_session_id: str,
        method: str,
        params: dict[str, Any],
        options: SessionSendOptions | None = None,
    ) -> Any:
        """Send a method call to a session.

        Args:
            local_session_id: The local session ID.
            method: The method name.
            params: Method parameters.
            options: Optional send options.

        Returns:
            Method result or None for notifications.

        Raises:
            RuntimeError if session is not bound to this connection.
        """
        options = options or {}
        agent_session_id = self._session_by_local_id.get(local_session_id)
        if not agent_session_id:
            raise RuntimeError(
                f"Session '{local_session_id}' is not bound to live ACP connection '{self.connection_id}'"
            )

        # Map session ID in params
        mapped_params = dict(params)
        if "sessionId" in mapped_params:
            mapped_params["sessionId"] = agent_session_id

        # Handle special methods
        if method == "session/prompt":
            # Check for pending replay
            replay_text = self._pending_replay_by_local_session_id.get(local_session_id)
            if replay_text:
                self._pending_replay_by_local_session_id.pop(local_session_id, None)
                _inject_replay_prompt(mapped_params, replay_text)

            if options.get("notification"):
                await self._acp.ext_notification(method, mapped_params)
                return None

            return await self._acp.prompt(mapped_params)

        if method == "session/cancel":
            await self._acp.cancel(mapped_params)
            return None

        if method == "session/set_mode":
            return await self._acp.set_session_mode(mapped_params)

        if method == "session/set_config_option":
            return await self._acp.set_session_config_option(mapped_params)

        # Generic method
        if options.get("notification"):
            await self._acp.ext_notification(method, mapped_params)
            return None

        return await self._acp.ext_method(method, mapped_params)

    def _handle_envelope(self, envelope: dict[str, Any], direction: str) -> None:
        """Handle an observed envelope.

        Args:
            envelope: The JSON-RPC envelope.
            direction: The direction ("outbound" or "inbound").
        """
        local_session_id = self._resolve_session_id(envelope, direction)
        self._on_observed_envelope(self, envelope, direction, local_session_id)

    def _handle_adapter_notification(self, method: str, params: dict[str, Any]) -> None:
        """Handle adapter notifications."""
        if method != "_adapter/agent_exited":
            return

        self._last_adapter_exit = {
            "success": params.get("success") is True,
            "code": params.get("code") if isinstance(params.get("code"), int) else None,
        }
        self._last_adapter_exit_at = _now_ms()

    async def _handle_permission_request(self, request: RequestPermissionRequest) -> PermissionResponse:
        """Handle a permission request from the agent.

        Args:
            request: The permission request.

        Returns:
            The permission response.
        """
        agent_session_id = request.get("sessionId", "")
        local_session_id = self._local_by_agent_session_id.get(agent_session_id)
        if not local_session_id:
            return _cancelled_permission_response()

        # Create a future for the response
        future = self._on_permission_request(
            self,
            local_session_id,
            agent_session_id,
            _clone_permission_request(request),
        )

        try:
            response = await future
            return response
        except Exception as e:
            logger.warning(f"Error handling permission request: {e}")
            return _cancelled_permission_response()

    def _resolve_session_id(self, envelope: dict[str, Any], direction: str) -> str | None:
        """Resolve the local session ID from an envelope.

        Args:
            envelope: The JSON-RPC envelope.
            direction: The direction ("outbound" or "inbound").

        Returns:
            The local session ID or None if not found.
        """
        msg_id = _envelope_id(envelope)
        method = _envelope_method(envelope)

        if direction == AcpEnvelopeDirection.OUTBOUND:
            if msg_id and method == "session/new":
                local_session_id = self._pending_new_session_locals.pop(0) if self._pending_new_session_locals else None
                if local_session_id:
                    self._pending_request_session_by_id[msg_id] = local_session_id
                return local_session_id

            local_from_params = self._local_from_envelope_params(envelope)
            if msg_id and local_from_params:
                self._pending_request_session_by_id[msg_id] = local_from_params
            return local_from_params

        # Inbound
        if msg_id:
            pending = self._pending_request_session_by_id.pop(msg_id, None)
            if pending:
                session_id_from_result = _envelope_session_id_from_result(envelope)
                if session_id_from_result:
                    self.bind_session(pending, session_id_from_result)
                return pending

        return self._local_from_envelope_params(envelope)

    def _local_from_envelope_params(self, envelope: dict[str, Any]) -> str | None:
        """Get local session ID from envelope params."""
        agent_session_id = _envelope_session_id_from_params(envelope)
        if not agent_session_id:
            return None
        return self._local_by_agent_session_id.get(agent_session_id)

    async def get_replay_text(
        self,
        session_id: str,
        events: list[SessionEvent],
        max_chars: int = DEFAULT_REPLAY_MAX_CHARS,
    ) -> str | None:
        """Build replay text for a session from its events.

        Args:
            session_id: The session ID.
            events: List of session events.
            max_chars: Maximum characters for replay text.

        Returns:
            Replay text or None if no events.
        """
        return _build_replay_text(events, max_chars)

    def observe_envelope(
        self,
        envelope: dict[str, Any],
        direction: str,
        local_session_id: str | None,
    ) -> None:
        """Observe an envelope for potential persistence.

        This is a convenience method that calls the on_observed_envelope callback.

        Args:
            envelope: The JSON-RPC envelope.
            direction: The direction ("outbound" or "inbound").
            local_session_id: The local session ID if known.
        """
        self._on_observed_envelope(self, envelope, direction, local_session_id)

    def queue_permission(
        self,
        local_session_id: str,
        agent_session_id: str,
        request: RequestPermissionRequest,
    ) -> asyncio.Future[RequestPermissionResponse]:
        """Queue a permission request for handling.

        Args:
            local_session_id: The local session ID.
            agent_session_id: The agent session ID.
            request: The permission request.

        Returns:
            A future that resolves to the permission response.
        """
        return self._on_permission_request(
            self,
            local_session_id,
            agent_session_id,
            _clone_permission_request(request),
        )

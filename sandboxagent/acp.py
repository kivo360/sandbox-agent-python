"""ACP (Agent Communication Protocol) HTTP client for agent communication.

This module provides an async HTTP client for the Agent Communication Protocol (ACP),
using Server-Sent Events (SSE) for receiving messages and HTTP POST for sending
JSON-RPC requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any, ClassVar, TypedDict, cast

import httpx

from sandboxagent.types import ProblemDetails

logger = logging.getLogger(__name__)

DEFAULT_ACP_PATH = "/v1/acp"
# ACP protocol revision number. The server validates this as an integer
# (zod number schema). The string `"2025-03-18"` was the date label of the
# protocol but is not the wire value — Rust/TS SDKs send the integer
# revision (currently 1). Verified via direct curl probe 2026-04-26.
PROTOCOL_VERSION = 1


class AcpHttpError(Exception):
    """Error raised when an ACP HTTP request fails."""

    def __init__(
        self,
        status: int,
        problem: ProblemDetails | dict[str, Any] | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        if isinstance(problem, ProblemDetails):
            title = problem.title
        elif isinstance(problem, dict):
            title = problem.get("title", f"Request failed with status {status}")
        else:
            title = f"Request failed with status {status}"
        super().__init__(title)
        self.status = status
        self.problem = problem
        self.response = response


class AcpRpcError(Exception):
    """Error raised when an ACP JSON-RPC call returns an error."""

    RPC_CODE_LABELS: ClassVar[dict[int, str]] = {
        -32700: "Parse error",
        -32600: "Invalid request",
        -32601: "Method not supported by agent",
        -32602: "Invalid parameters",
        -32603: "Internal agent error",
        -32000: "Authentication required",
        -32002: "Resource not found",
    }

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        label = self.RPC_CODE_LABELS.get(code)
        display = f"{label}: {message}" if label else message
        super().__init__(display)
        self.code = code
        self.message = message
        self.data = data


class InitializeRequest(TypedDict, total=False):
    """Request to initialize the ACP connection."""

    protocolVersion: str
    clientCapabilities: dict[str, Any]
    clientInfo: dict[str, str]
    _meta: dict[str, Any]


class InitializeResponse(TypedDict):
    """Response from initialize request."""

    protocolVersion: str
    capabilities: dict[str, Any]
    serverInfo: dict[str, str]


class AuthenticateRequest(TypedDict):
    """Request to authenticate with the agent."""

    token: str


class AuthenticateResponse(TypedDict, total=False):
    """Response from authenticate request."""

    success: bool
    error: str | None


class NewSessionRequest(TypedDict, total=False):
    """Request to create a new session."""

    agent: str
    sessionInit: dict[str, Any]
    configOptions: list[dict[str, Any]]
    modes: dict[str, Any]


class NewSessionResponse(TypedDict):
    """Response from new session request."""

    sessionId: str
    agentSessionId: str


class LoadSessionRequest(TypedDict):
    """Request to load an existing session."""

    sessionId: str


class LoadSessionResponse(TypedDict, total=False):
    """Response from load session request."""

    sessionId: str
    agentSessionId: str
    error: str | None


class PromptRequest(TypedDict, total=False):
    """Request to send a prompt to the agent."""

    sessionId: str
    prompt: str
    attachments: list[dict[str, Any]]
    streaming: bool


class PromptResponse(TypedDict, total=False):
    """Response from prompt request."""

    content: str
    error: str | None


class CancelNotification(TypedDict):
    """Notification to cancel an ongoing operation."""

    sessionId: str
    requestId: str


class SetSessionModeRequest(TypedDict):
    """Request to set the session mode."""

    sessionId: str
    mode: str


class SetSessionModeResponse(TypedDict, total=False):
    """Response from set session mode request."""

    success: bool
    error: str | None


class SetSessionConfigOptionRequest(TypedDict):
    """Request to set a session config option."""

    sessionId: str
    configId: str
    value: Any


class SetSessionConfigOptionResponse(TypedDict, total=False):
    """Response from set session config option request."""

    success: bool
    error: str | None


class ListSessionsRequest(TypedDict, total=False):
    """Request to list sessions."""

    cursor: str | None
    limit: int | None


class ListSessionsResponse(TypedDict):
    """Response from list sessions request."""

    sessions: list[dict[str, Any]]
    nextCursor: str | None


class PermissionRequest(TypedDict):
    """Permission request from the agent."""

    id: str
    sessionId: str
    permission: dict[str, Any]


class PermissionResponse(TypedDict):
    """Response to a permission request."""

    id: str
    outcome: dict[str, Any]


MessageHandler = Callable[[dict[str, Any]], None]
ErrorHandler = Callable[[Exception], None]
CloseHandler = Callable[[], None]
PermissionHandler = Callable[[PermissionRequest], PermissionResponse]


class AcpHttpClient:
    """HTTP client for the Agent Communication Protocol (ACP).

    This client communicates with an ACP server using:
    - Server-Sent Events (SSE) for receiving messages from the agent
    - HTTP POST for sending JSON-RPC requests to the agent

    Example:
        client = AcpHttpClient("http://localhost:2468", server_id="my-server")
        await client.connect()

        # Initialize the connection
        init_response = await client.initialize()

        # Create a session
        session = await client.new_session({"agent": "claude"})

        # Send a prompt
        response = await client.prompt({
            "sessionId": session["agentSessionId"],
            "prompt": "Hello!"
        })

        await client.disconnect()
    """

    def __init__(
        self,
        base_url: str,
        server_id: str,
        *,
        agent: str | None = None,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        on_message: MessageHandler | None = None,
        on_error: ErrorHandler | None = None,
        on_close: CloseHandler | None = None,
        on_permission_request: PermissionHandler | None = None,
    ) -> None:
        """Initialize the ACP HTTP client.

        Args:
            base_url: Base URL of the sandbox-agent server.
            server_id: ID of the ACP server instance to connect to.
            agent: Agent type for this server (e.g. "claude", "codex",
                "opencode"). Required by the server on the first POST to
                /v1/acp/{server_id} as a query parameter to bootstrap the
                ACP runtime; ignored on subsequent requests.
            token: Optional bearer token for authentication.
            headers: Optional additional HTTP headers.
            timeout: HTTP request timeout in seconds.
            on_message: Callback for incoming messages.
            on_error: Callback for errors.
            on_close: Callback when connection closes.
            on_permission_request: Callback for permission requests.
        """
        self._base_url = base_url.rstrip("/")
        self._server_id = server_id
        self._agent = agent
        self._first_post_sent = False
        self._token = token
        self._timeout = timeout
        self._closed = False
        self._connected = False

        # Event handlers
        self._on_message = on_message
        self._on_error = on_error
        self._on_close = on_close
        self._on_permission_request = on_permission_request

        # HTTP client
        default_headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=default_headers,
            timeout=timeout,
        )

        # SSE state
        self._sse_task: asyncio.Task[None] | None = None
        self._sse_abort = False
        self._last_event_id: str | None = None

        # JSON-RPC state
        self._request_id = 0
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._session_id_map: dict[str, str] = {}
        self._lock = asyncio.Lock()
        # Session ID mapping (local_session_id -> agent_session_id)
        self._session_id_map: dict[str, str] = {}
        self._reverse_session_id_map: dict[str, str] = {}

        # Seen response IDs for deduplication
        self._seen_response_ids: set[str] = set()
        self._seen_response_id_order: list[str] = []

        # Permission request task reference
        self._permission_task: asyncio.Task[None] | None = None

    @property
    def on_message(self) -> MessageHandler | None:
        """Get the message handler callback."""
        return self._on_message

    @on_message.setter
    def on_message(self, handler: MessageHandler | None) -> None:
        """Set the message handler callback."""
        self._on_message = handler

    @property
    def on_error(self) -> ErrorHandler | None:
        """Get the error handler callback."""
        return self._on_error

    @on_error.setter
    def on_error(self, handler: ErrorHandler | None) -> None:
        """Set the error handler callback."""
        self._on_error = handler

    @property
    def on_close(self) -> CloseHandler | None:
        """Get the close handler callback."""
        return self._on_close

    @on_close.setter
    def on_close(self, handler: CloseHandler | None) -> None:
        """Set the close handler callback."""
        self._on_close = handler

    @property
    def on_permission_request(self) -> PermissionHandler | None:
        """Permission request handler."""
        return self._on_permission_request

    @on_permission_request.setter
    def on_permission_request(self, handler: PermissionHandler | None) -> None:
        """Set the permission request handler."""
        self._on_permission_request = handler

    def _get_next_request_id(self) -> str:
        """Generate the next JSON-RPC request ID."""
        self._request_id += 1
        return str(self._request_id)

    def _build_url(self, path: str | None = None) -> str:
        """Build the full URL for ACP endpoints."""
        base_path = f"{DEFAULT_ACP_PATH}/{self._server_id}"
        if path:
            return f"{self._base_url}{base_path}{path}"
        return f"{self._base_url}{base_path}"

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build HTTP headers with optional authentication."""
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if extra:
            headers.update(extra)
        return headers

    def _map_session_id(self, local_session_id: str) -> str:
        """Map a local session ID to an agent session ID."""
        return self._session_id_map.get(local_session_id, local_session_id)

    def _map_params_session_ids(self, params: dict[str, Any]) -> dict[str, Any]:
        """Map session IDs in params from local to agent-side."""
        if not params:
            return params

        mapped = dict(params)
        if "sessionId" in mapped:
            mapped["sessionId"] = self._map_session_id(mapped["sessionId"])
        return mapped

    async def connect(self) -> None:
        """Connect to the ACP server and start the SSE listener.

        Raises:
            AcpHttpError: If the connection fails.
        """
        if self._connected:
            return

        self._closed = False
        self._sse_abort = False

        # Start SSE listener
        self._sse_task = asyncio.create_task(self._sse_loop())
        self._connected = True

    async def _sse_loop(self) -> None:
        """Main SSE listening loop."""
        retry_delay = 0.5

        while not self._closed and not self._sse_abort:
            try:
                headers = self._build_headers({
                    "Accept": "text/event-stream",
                })

                if self._last_event_id:
                    headers["Last-Event-ID"] = self._last_event_id

                async with self._client.stream(
                    "GET",
                    self._build_url(),
                    headers=headers,
                    timeout=None,  # SSE connections are long-lived
                ) as response:
                    if response.status_code >= 400:
                        error_body = await response.aread()
                        problem = None
                        try:
                            problem_data = json.loads(error_body)
                            problem = ProblemDetails.model_validate(problem_data)
                        except Exception:
                            problem = None
                        raise AcpHttpError(
                            response.status_code,
                            problem,
                            response,
                        )

                    # Process SSE stream
                    await self._consume_sse(response)

                # If we get here cleanly, reset retry delay
                retry_delay = 0.5
                await asyncio.sleep(0)  # Yield to prevent tight loop
                retry_delay = 0.5

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._closed or self._sse_abort:
                    break

                logger.warning(f"SSE connection error: {e}")

                if self._on_error:
                    with suppress(Exception):
                        self._on_error(e)

                # Wait before reconnecting
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 15.0)

    async def _consume_sse(self, response: httpx.Response) -> None:
        """Consume and process the SSE stream."""
        buffer = ""

        async for chunk in response.aiter_text():
            buffer += chunk.replace("\r\n", "\n")

            # Process complete events (separated by \n\n)
            while "\n\n" in buffer:
                separator_index = buffer.index("\n\n")
                event_chunk = buffer[:separator_index]
                buffer = buffer[separator_index + 2:]
                self._process_sse_event(event_chunk)

    def _process_sse_event(self, chunk: str) -> None:
        """Process a single SSE event."""
        if not chunk.strip():
            return

        event_name = "message"
        event_id: str | None = None
        data_lines: list[str] = []

        for line in chunk.split("\n"):
            if not line or line.startswith(":"):
                continue

            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue

            if line.startswith("id:"):
                event_id = line[3:].strip()
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if event_id:
            self._last_event_id = event_id

        if event_name != "message" or not data_lines:
            return

        payload_text = "\n".join(data_lines)
        if not payload_text.strip():
            return

        try:
            envelope = json.loads(payload_text)
            self._process_inbound_message(envelope)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse SSE payload: {e}")

    def _process_inbound_message(self, envelope: dict[str, Any]) -> None:
        """Process an inbound JSON-RPC message."""
        # Deduplicate responses
        response_id = self._get_response_id(envelope)
        if response_id:
            if response_id in self._seen_response_ids:
                return
            self._seen_response_ids.add(response_id)
            self._seen_response_id_order.append(response_id)

            # Limit dedup set size
            if len(self._seen_response_id_order) > 2048:
                oldest = self._seen_response_id_order.pop(0)
                self._seen_response_ids.discard(oldest)

        # Handle permission requests
        method = envelope.get("method")
        if method == "session/request_permission":
            self._permission_task = asyncio.create_task(self._handle_permission_request(envelope))
            return

        # Check if this is a response to a pending request
        msg_id = envelope.get("id")
        if msg_id is not None and msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if not future.done():
                future.set_result(envelope)
            return

        # Call the message handler for other messages
        if self._on_message:
            with suppress(Exception):
                self._on_message(envelope)

    def _get_response_id(self, envelope: dict[str, Any]) -> str | None:
        """Extract the response ID from an envelope for deduplication."""
        if not isinstance(envelope, dict):
            return None

        # Requests have a method, responses don't
        if "method" in envelope:
            return None

        # Responses must have result or error
        if "result" not in envelope and "error" not in envelope:
            return None

        msg_id = envelope.get("id")
        if msg_id is None:
            return None

        return str(msg_id)

    async def _handle_permission_request(self, envelope: dict[str, Any]) -> None:
        """Handle a permission request from the agent."""
        if self._on_permission_request is None:
            # Auto-deny if no handler
            await self._send_permission_response(envelope, {"outcome": "cancelled"})
            return

        try:
            params = envelope.get("params", {})
            request = PermissionRequest(
                id=envelope.get("id", ""),
                sessionId=params.get("sessionId", ""),
                permission=params.get("permission", {}),
            )
            response = self._on_permission_request(request)
            await self._send_permission_response(envelope, response["outcome"])
        except Exception as e:
            logger.warning(f"Error handling permission request: {e}")
            await self._send_permission_response(envelope, {"outcome": "cancelled"})

    async def _send_permission_response(
        self,
        request_envelope: dict[str, Any],
        outcome: dict[str, Any],
    ) -> None:
        """Send a permission response back to the agent."""
        response = {
            "jsonrpc": "2.0",
            "id": request_envelope.get("id"),
            "result": {"outcome": outcome},
        }
        await self._send_message(response)

    async def _send_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC message via HTTP POST.

        Args:
            message: The JSON-RPC message to send.

        Returns:
            The response envelope if the server returns one synchronously,
            or None for notifications.

        Raises:
            AcpHttpError: If the HTTP request fails.
            AcpRpcError: If the JSON-RPC response contains an error.
        """
        if self._closed:
            raise RuntimeError("ACP client is closed")

        headers = self._build_headers({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # The server requires `?agent=<name>` on the first POST to
        # /v1/acp/{server_id} to bootstrap the ACP runtime for that agent
        # type. Subsequent requests reuse the runtime and don't need it.
        post_params: dict[str, str] | None = None
        if not self._first_post_sent and self._agent:
            post_params = {"agent": self._agent}

        try:
            response = await self._client.post(
                self._build_url(),
                headers=headers,
                json=message,
                params=post_params,
                timeout=self._timeout,
            )
            # Mark the first POST as done once we get any response from the
            # server (including errors) — retrying with ?agent= twice
            # would cause the server to reject the second one.
            self._first_post_sent = True

            if response.status_code >= 400:
                problem = None
                try:
                    data = response.json()
                    problem = ProblemDetails.model_validate(data)
                except Exception:
                    problem = None
                raise AcpHttpError(response.status_code, problem, response)

            # Handle synchronous response (200 with body)
            if response.status_code == 200:
                text = response.text
                if text.strip():
                    try:
                        envelope = response.json()
                        self._check_rpc_error(envelope)
                        return envelope
                    except json.JSONDecodeError:
                        pass

            return None

        except httpx.HTTPError as e:
            raise AcpHttpError(0, {"title": f"HTTP error: {e}"}) from e

    def _check_rpc_error(self, envelope: dict[str, Any]) -> None:
        """Check if an envelope contains a JSON-RPC error and raise if so."""
        if "error" in envelope and envelope["error"] is not None:
            error = envelope["error"]
            if isinstance(error, dict):
                code = error.get("code", -32603)
                message = error.get("message", "Unknown error")
                data = error.get("data")
                raise AcpRpcError(code, message, data)

    async def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response.

        Args:
            method: The JSON-RPC method name.
            params: The method parameters.

        Returns:
            The result from the JSON-RPC response.

        Raises:
            AcpRpcError: If the response contains an error.
            RuntimeError: If the client is closed.
        """
        request_id = self._get_next_request_id()

        # Map session IDs in params
        mapped_params = self._map_params_session_ids(params) if params else None

        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if mapped_params is not None:
            message["params"] = mapped_params

        # Create a future to wait for the response
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            sync_response = await self._send_message(message)
            if sync_response is not None:
                # Server returned response synchronously in POST body
                return sync_response.get("result", {})

            # Wait for the response via SSE
            response = await asyncio.wait_for(future, timeout=self._timeout)

            if "error" in response and response["error"] is not None:
                error = response["error"]
                raise AcpRpcError(
                    error.get("code", -32603),
                    error.get("message", "Unknown error"),
                    error.get("data"),
                )

            return response.get("result", {})
            await self._send_message(message)

            # Wait for the response with timeout
            response = await asyncio.wait_for(future, timeout=self._timeout)

            if "error" in response and response["error"] is not None:
                error = response["error"]
                raise AcpRpcError(
                    error.get("code", -32603),
                    error.get("message", "Unknown error"),
                    error.get("data"),
                )

            return response.get("result", {})

        except asyncio.TimeoutError:
            raise AcpRpcError(-32603, f"Request timeout for method '{method}'") from None
        finally:
            self._pending_requests.pop(request_id, None)

    async def _send_notification(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: The JSON-RPC method name.
            params: The method parameters.
        """
        # Map session IDs in params
        mapped_params = self._map_params_session_ids(params) if params else None

        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if mapped_params is not None:
            message["params"] = mapped_params

        await self._send_message(message)

    async def initialize(
        self,
        request: InitializeRequest | None = None,
    ) -> InitializeResponse:
        """Initialize the ACP connection.

        Args:
            request: Optional initialization parameters.

        Returns:
            The initialization response from the agent.
        """
        params: InitializeRequest = {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {},
            "clientInfo": {
                "name": "sandboxagent-python",
                "version": "0.2.0",
            },
        }
        if request:
            params.update(request)

        result = await self._send_request("initialize", cast(dict[str, Any], params))
        return cast(InitializeResponse, result)

    async def authenticate(
        self,
        request: AuthenticateRequest,
    ) -> AuthenticateResponse:
        """Authenticate with the agent.

        Args:
            request: Authentication credentials.

        Returns:
            The authentication response.
        """
        result = await self._send_request("authenticate", cast(dict[str, Any], request))
        return cast(AuthenticateResponse, result)

    async def new_session(
        self,
        request: NewSessionRequest,
    ) -> NewSessionResponse:
        """Create a new session.

        Args:
            request: New session parameters.

        Returns:
            The new session response with session IDs.
        """
        result = await self._send_request("session/new", cast(dict[str, Any], request))

        # Store session ID mapping
        local_id = result.get("sessionId")
        agent_id = result.get("agentSessionId")
        if local_id and agent_id:
            self._session_id_map[local_id] = agent_id
            self._reverse_session_id_map[agent_id] = local_id

        return cast(NewSessionResponse, result)

    async def load_session(
        self,
        request: LoadSessionRequest,
    ) -> LoadSessionResponse:
        """Load an existing session.

        Args:
            request: Load session parameters.

        Returns:
            The load session response.
        """
        result = await self._send_request("session/load", cast(dict[str, Any], request))

        # Store session ID mapping
        local_id = result.get("sessionId")
        agent_id = result.get("agentSessionId")
        if local_id and agent_id:
            self._session_id_map[local_id] = agent_id
            self._reverse_session_id_map[agent_id] = local_id

        return cast(LoadSessionResponse, result)

    async def prompt(
        self,
        request: PromptRequest,
    ) -> PromptResponse:
        """Send a prompt to the agent.

        Args:
            request: Prompt parameters including session ID and prompt text.

        Returns:
            The prompt response.
        """
        result = await self._send_request("session/prompt", cast(dict[str, Any], request))
        return cast(PromptResponse, result)

    async def cancel(
        self,
        notification: CancelNotification,
    ) -> None:
        """Cancel an ongoing operation.

        Args:
            notification: Cancel notification with session ID and request ID.
        """
        await self._send_notification("session/cancel", cast(dict[str, Any], notification))

    async def set_session_mode(
        self,
        request: SetSessionModeRequest,
    ) -> SetSessionModeResponse:
        """Set the mode for a session.

        Args:
            request: Set session mode parameters.

        Returns:
            The set session mode response.
        """
        result = await self._send_request("session/set_mode", cast(dict[str, Any], request))
        return cast(SetSessionModeResponse, result)

    async def set_session_config_option(
        self,
        request: SetSessionConfigOptionRequest,
    ) -> SetSessionConfigOptionResponse:
        """Set a config option for a session.

        Args:
            request: Set session config option parameters.

        Returns:
            The set session config option response.
        """
        result = await self._send_request("session/set_config_option", cast(dict[str, Any], request))
        return cast(SetSessionConfigOptionResponse, result)

    async def list_sessions(
        self,
        request: ListSessionsRequest | None = None,
    ) -> ListSessionsResponse:
        """List all sessions.

        Args:
            request: Optional list sessions parameters.

        Returns:
            The list sessions response.
        """
        result = await self._send_request("session/list", cast(dict[str, Any], request or {}))
        return cast(ListSessionsResponse, result)

    async def ext_method(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an extension method.

        Args:
            method: The extension method name.
            params: The method parameters.

        Returns:
            The method result.
        """
        result = await self._send_request(method, params)
        return result

    async def ext_notification(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """Send an extension notification.

        Args:
            method: The extension method name.
            params: The method parameters.
        """
        await self._send_notification(method, params)

    async def disconnect(self) -> None:
        """Disconnect from the ACP server and clean up resources."""
        if self._closed:
            return

        self._closed = True
        self._sse_abort = True

        # Cancel SSE task
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._sse_task

        # Send DELETE request to close the connection
        try:
            headers = self._build_headers({
                "Accept": "application/json",
            })
            response = await self._client.delete(
                self._build_url(),
                headers=headers,
                timeout=2.0,
            )
            # 404 is acceptable (already closed)
            if response.status_code >= 400 and response.status_code != 404:
                logger.warning(f"Error closing ACP connection: {response.status_code}")
        except Exception as e:
            logger.debug(f"Error during disconnect: {e}")

        # Close HTTP client
        await self._client.aclose()

        # Clear pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        self._connected = False

        # Call close handler
        if self._on_close:
            with suppress(Exception):
                self._on_close()

    async def __aenter__(self) -> AcpHttpClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

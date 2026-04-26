"""SandboxAgent client — main entry point for the SDK."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
import logging
import time
import uuid

from sandboxagent.persistence import InMemorySessionPersistDriver, SessionPersistDriver

from sandboxagent.acp import (
    AcpHttpClient,
    InitializeRequest,
    InitializeResponse,
    NewSessionRequest,
    NewSessionResponse,
    PermissionRequest,
    PermissionResponse,
    PromptRequest,
    PromptResponse,
)
from sandboxagent.http import HttpTransport, SandboxAgentError
from sandboxagent.sse_streaming import ProcessLogSubscription
from sandboxagent.terminal import ProcessTerminalSession
from sandboxagent.types import (
    SessionRecord,
)
try:
    from sandboxagent.providers import SandboxProvider
except ImportError:
    SandboxProvider = None  # type: ignore[misc,assignment]
from sandboxagent.inspector import build_inspector_url

API_PREFIX = "/v1"
DEFAULT_BASE_URL = "http://sandbox-agent"
HEALTH_WAIT_MIN_DELAY = 0.5
HEALTH_WAIT_MAX_DELAY = 15.0


class SandboxDestroyedError(Exception):
    """Raised when the sandbox no longer exists."""

    def __init__(self, sandbox_id: str, provider: str) -> None:
        super().__init__(f"Sandbox '{provider}/{sandbox_id}' no longer exists and cannot be reconnected.")
        self.sandbox_id = sandbox_id
        self.provider = provider


class UnsupportedSessionCategoryError(Exception):
    """Raised when a session does not support the requested category."""

    def __init__(self, session_id: str, category: str, available_categories: list[str]) -> None:
        cats = ", ".join(available_categories) or "(none)"
        super().__init__(f"Session '{session_id}' does not support category '{category}'. Available: {cats}")
        self.session_id = session_id
        self.category = category
        self.available_categories = available_categories


class UnsupportedSessionValueError(Exception):
    """Raised when a session does not support the requested value."""

    def __init__(
        self, session_id: str, category: str, config_id: str, requested_value: str, allowed_values: list[str]
    ) -> None:
        vals = ", ".join(allowed_values) or "(none)"
        super().__init__(
            f"Session '{session_id}' does not support value '{requested_value}' "
            f"for category '{category}' (configId='{config_id}'). Allowed: {vals}"
        )
        self.session_id = session_id
        self.category = category
        self.config_id = config_id
        self.requested_value = requested_value
        self.allowed_values = allowed_values


class UnsupportedSessionConfigOptionError(Exception):
    """Raised when a session does not expose the requested config option."""

    def __init__(self, session_id: str, config_id: str, available_config_ids: list[str]) -> None:
        ids = ", ".join(available_config_ids) or "(none)"
        super().__init__(f"Session '{session_id}' does not expose config option '{config_id}'. Available: {ids}")
        self.session_id = session_id
        self.config_id = config_id
        self.available_config_ids = available_config_ids


class UnsupportedPermissionReplyError(Exception):
    """Raised when a permission does not support the requested reply."""

    def __init__(self, permission_id: str, requested_reply: str, available_replies: list[str]) -> None:
        replies = ", ".join(available_replies) or "(none)"
        super().__init__(
            f"Permission '{permission_id}' does not support reply "
            f"'{requested_reply}'. Available: {replies}"
        )
        self.permission_id = permission_id
        self.requested_reply = requested_reply
        self.available_replies = available_replies



class DesktopNotSupportedError(Exception):
    """Raised when desktop streaming is not supported on the current platform.

    This typically occurs when the server returns HTTP 501 Not Implemented,
    indicating that desktop APIs are only available on Linux sandboxes.
    """

    def __init__(
        self,
        message: str = (
            "Desktop streaming is Unsupported on this platform. "
            "Only Linux sandboxes support desktop APIs."
        ),
    ) -> None:
        super().__init__(message)
        self.message = message


class GitCloneError(Exception):
    """Raised when a git clone operation fails."""

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message)
        self.category = category  # "auth", "not_found", "network", "unknown"


class Session:
    """Represents an active ACP session with an agent."""

    def __init__(
        self,
        sandbox: SandboxAgent,
        record: SessionRecord,
        acp_client: AcpHttpClient | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._record = _clone_session_record(record)
        self._acp = acp_client
        self._permission_callback: Callable[[PermissionRequest], PermissionResponse] | None = None
        self._events: list[dict[str, Any]] = []
        self._track_events = False
        self._original_on_message: Callable[[dict[str, Any]], None] | None = None
        self._tracking_active = False
    @property
    def id(self) -> str:
        return self._record.id

    @property
    def agent(self) -> str:
        return self._record.agent

    @property
    def agent_session_id(self) -> str:
        return self._record.agent_session_id

    @property
    def created_at(self) -> int:
        return self._record.created_at

    @property
    def destroyed_at(self) -> int | None:
        return self._record.destroyed_at

    @property
    def acp_client(self) -> AcpHttpClient | None:
        """Get the ACP HTTP client associated with this session."""
        return self._acp

    def to_record(self) -> SessionRecord:
        return _clone_session_record(self._record)

    def _ensure_acp(self) -> AcpHttpClient:
        """Ensure ACP client is available, raising an error if not."""
        if self._acp is None:
            raise RuntimeError("Session is not connected to an ACP client")
        return self._acp

    # --- Event Handlers ---

    def on_message(self, handler: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
        """Register a callback for incoming messages from the agent.

        Args:
            handler: Callback function that receives message dictionaries.

        Returns:
            The registered handler (for use as a decorator).
        """
        acp = self._ensure_acp()
        acp.on_message = handler
        return handler

    def on_error(self, handler: Callable[[Exception], None]) -> Callable[[Exception], None]:
        """Register a callback for errors from the ACP connection.

        Args:
            handler: Callback function that receives exceptions.

        Returns:
            The registered handler (for use as a decorator).
        """
        acp = self._ensure_acp()
        acp.on_error = handler
        return handler

    def on_close(self, handler: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for when the ACP connection closes.

        Args:
            handler: Callback function with no arguments.

        Returns:
            The registered handler (for use as a decorator).
        """
        acp = self._ensure_acp()
        acp.on_close = handler
        return handler

    def set_permission_callback(
        self,
        callback: Callable[[PermissionRequest], PermissionResponse] | None,
    ) -> None:
        """Set a callback for handling permission requests from the agent.

        If no callback is set, permission requests are automatically denied.

        Args:
            callback: Function that receives a PermissionRequest and returns
                a PermissionResponse, or None to auto-deny all permissions.
        """
        self._permission_callback = callback
        acp = self._ensure_acp()
        acp.on_permission_request = callback

    def track_events(self, enabled: bool = True) -> None:
        """Enable or disable event tracking for this session.

        When enabled, all incoming messages are stored in memory for later
        replay via `get_transcript()`.
        """
        self._track_events = enabled
        if enabled and self._acp:
            if self._tracking_active:
                return
            self._tracking_active = True
            if self._original_on_message is None:
                self._original_on_message = self._acp.on_message

            def _tracking_handler(message: dict[str, Any]) -> None:
                if self._track_events:
                    self._events.append({
                        "timestamp": int(time.time()),
                        "role": message.get("role", "agent"),
                        "content": json.dumps(message),
                    })
                if self._original_on_message:
                    self._original_on_message(message)

            self._acp.on_message = _tracking_handler
        elif not enabled and self._acp:
            self._tracking_active = False
            if self._original_on_message:
                self._acp.on_message = self._original_on_message
                self._original_on_message = None

    def get_transcript(self, max_events: int = 100) -> str:
        """Get a text transcript of session events.

        Args:
            max_events: Maximum number of recent events to include.

        Returns:
            Formatted transcript string.
        """
        if not self._events:
            return "(no events recorded)"

        lines = [f"# Session {self.id} transcript\n"]
        for event in self._events[-max_events:]:
            ts_raw = event.get("timestamp", "?")
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = str(ts_raw)
            role = event.get("role", "unknown")
            content = event.get("content", "")
            lines.append(f"[{ts}] {role}: {content}")

        return "\n".join(lines)

    # --- Session Lifecycle ---

    async def initialize(
        self,
        request: InitializeRequest | None = None,
    ) -> InitializeResponse:
        """Initialize the ACP connection for this session.

        Args:
            request: Optional initialization parameters.

        Returns:
            The initialization response from the agent.
        """
        acp = self._ensure_acp()
        await acp.connect()
        return await acp.initialize(request)

    async def authenticate(self, token: str) -> dict[str, Any]:
        """Authenticate with the agent.

        Args:
            token: Authentication token.

        Returns:
            The authentication response.
        """
        acp = self._ensure_acp()
        return await acp.authenticate({"token": token})

    async def new_session(
        self,
        agent: str,
        session_init: dict[str, Any] | None = None,
        config_options: list[dict[str, Any]] | None = None,
        modes: dict[str, Any] | None = None,
    ) -> NewSessionResponse:
        """Create a new session via ACP.

        Args:
            agent: The agent identifier.
            session_init: Optional session initialization parameters.
            config_options: Optional configuration options.
            modes: Optional session modes.

        Returns:
            The new session response with session IDs.
        """
        acp = self._ensure_acp()
        request: NewSessionRequest = {"agent": agent}
        if session_init:
            request["sessionInit"] = session_init
        if config_options:
            request["configOptions"] = config_options
        if modes:
            request["modes"] = modes
        return await acp.new_session(request)

    async def load_session(self, session_id: str) -> dict[str, Any]:
        """Load an existing session via ACP.

        Args:
            session_id: The session ID to load.

        Returns:
            The load session response.
        """
        acp = self._ensure_acp()
        return await acp.load_session({"sessionId": session_id})

    # --- Messaging ---

    async def prompt(
        self,
        prompt: str,
        attachments: list[dict[str, Any]] | None = None,
        streaming: bool = False,
    ) -> PromptResponse:
        """Send a prompt to the agent.

        Args:
            prompt: The prompt text to send.
            attachments: Optional list of file attachments.
            streaming: Whether to stream the response.

        Returns:
            The prompt response from the agent.

        Raises:
            RuntimeError: If no ACP client is connected.
            AcpRpcError: If the prompt fails.
        """
        acp = self._ensure_acp()
        # ACP `prompt` is an array of content parts (TS shape:
        # `[{type: "text", text: "..."}]`). The Python convenience signature
        # accepts a plain string and wraps it; advanced callers can pass a
        # pre-built list via `attachments` or call acp.prompt() directly.
        prompt_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if attachments:
            prompt_parts.extend(attachments)
        request: PromptRequest = {
            "sessionId": self._record.agent_session_id,
            "prompt": prompt_parts,
        }
        return await acp.prompt(request)

    # --- Process Terminal ---

    async def attach_terminal(
        self,
        process_id: str,
        *,
        on_data: Callable[[bytes], None] | None = None,
        on_exit: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> ProcessTerminalSession:
        """Attach to a process terminal via WebSocket.

        This method establishes a WebSocket connection to the process terminal,
        enabling interactive input/output with the process PTY.

        Args:
            process_id: The ID of the process to attach to.
            on_data: Optional callback for terminal data (PTY output).
            on_exit: Optional callback for process exit events.
            on_error: Optional callback for error events.

        Returns:
            A ProcessTerminalSession instance for interacting with the terminal.

        Raises:
            ConnectionError: If the WebSocket connection fails.
            RuntimeError: If the session is not connected to a sandbox.

        Example:
            >>> session = await session.attach_terminal("proc-123")
            >>> session.on_data(lambda data: print(data.decode()))
            >>> session.send_input("echo hello\\n")
            >>> await session.close()
        """
        from sandboxagent.terminal import connect_process_terminal

        base_url = self._sandbox._base_url
        token = self._sandbox._transport._token

        terminal_session = await connect_process_terminal(
            base_url=base_url,
            process_id=process_id,
            token=token,
        )

        # Register optional callbacks
        if on_data:
            terminal_session.on_data(on_data)
        if on_exit:
            terminal_session.on_exit(on_exit)
        if on_error:
            terminal_session.on_error(on_error)

        return terminal_session


    async def cancel(self, request_id: str) -> None:
        """Cancel an ongoing operation.

        Args:
            request_id: The request ID to cancel.
        """
        acp = self._ensure_acp()
        await acp.cancel({"sessionId": self._record.agent_session_id, "requestId": request_id})

    async def start_desktop(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> "DesktopStreamSession":  # noqa: UP037,F821
        """Start a desktop streaming session for this session.

        This initiates a WebRTC connection to the sandbox desktop, allowing
        real-time video streaming and input control via the Neko protocol.

        Args:
            width: Optional desired screen width
            height: Optional desired screen height

        Returns:
            A DesktopStreamSession instance for controlling the stream

        Raises:
            DesktopNotSupportedError: If the server returns 501 (desktop not available on this platform)
            SandboxAgentError: If the server returns another error status
            RuntimeError: If no ACP client is connected

        Example:
            desktop = await session.start_desktop()

            # Listen for video
            desktop.on_track(lambda track: print(f"Track: {track}"))

            # Wait for ready
            def on_ready(status):
                print(f"Desktop ready: {status.width}x{status.height}")
            desktop.on_ready(on_ready)

            # Control input
            desktop.move_mouse(100, 200)
            desktop.mouse_click("left")
            desktop.key_press("Enter")

            desktop.close()
        """
        raise DesktopNotSupportedError(
            "Desktop streaming is not supported. "
            "Install sandboxagent[desktop] for desktop features."
        )

    # --- Session-scoped MCP and Skills Config ---

    async def get_mcp_config(self) -> dict[str, Any]:
        """Get MCP server configuration for this session.

        Returns:
            The MCP server configuration for the session.

        Raises:
            SandboxAgentError: If the request fails (e.g., 404 if no session context).
        """
        response = await self._sandbox._transport.get(
            f"{API_PREFIX}/sessions/{self.id}/mcp/config"
        )
        return response.json()



    async def set_mcp_config(self, config: dict[str, Any]) -> None:
        """Set MCP server configuration for this session.

        Args:
            config: The MCP server configuration to set.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._sandbox._transport.put(
            f"{API_PREFIX}/sessions/{self.id}/mcp/config",
            json=config,
        )

    async def get_skills_config(self) -> dict[str, Any]:
        """Get skills configuration for this session.

        Returns:
            The skills configuration for the session.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._sandbox._transport.get(
            f"{API_PREFIX}/sessions/{self.id}/skills/config"
        )
        return response.json()

    async def set_skills_config(self, config: dict[str, Any]) -> None:
        """Set skills configuration for this session.

        Args:
            config: The skills configuration to set.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._sandbox._transport.put(
            f"{API_PREFIX}/sessions/{self.id}/skills/config",
            json=config,
        )

    async def register_custom_tool(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a custom tool for this session.

        Args:
            name: The name of the custom tool.
            handler: The function to handle tool invocations.
            description: Optional description of the tool.
            schema: Optional JSON schema for the tool parameters.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no ACP client is connected.
        """
        acp = self._ensure_acp()
        await acp.register_custom_tool(name, handler, description, schema)

    async def unregister_custom_tool(self, name: str) -> None:
        """Unregister a custom tool for this session.

        Args:
            name: The name of the custom tool to unregister.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no ACP client is connected.
        """
        acp = self._ensure_acp()
        await acp.unregister_custom_tool(name)


def _escape_dotenv_value(value: str) -> str:
    """Escape a value for a double-quoted .env assignment."""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace('"', '\\"')
    )


def _merge_env_into_provider(provider: SandboxProvider, workspace_env: dict[str, str]) -> None:
    """Merge workspace_env into a provider's env configuration.

    Checks if the provider has an `env` attribute or `set_env` method and
    merges the workspace_env accordingly. Validates that all env values are strings.

    Args:
        provider: The sandbox provider to configure.
        workspace_env: Environment variables to inject into the sandbox.
    """
    for key, value in workspace_env.items():
        if not isinstance(value, str):
            raise TypeError(f"Environment variable '{key}' must be a string, got {type(value).__name__}")

    existing_env = getattr(provider, "env", None)
    merged_env = {**existing_env, **workspace_env} if existing_env is not None else workspace_env

    if hasattr(provider, "set_env"):
        provider.set_env(merged_env)
    elif hasattr(provider, "env"):
        provider.env = merged_env


class SandboxAgent:
    """Client for interacting with a SandboxAgent server."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        skip_health_check: bool = False,
        *,
        persistence: SessionPersistDriver | None = None,
    ) -> None:
        """Initialize the SandboxAgent client.

        Args:
            base_url: The base URL of the SandboxAgent server.
            token: Optional authentication token.
            headers: Optional additional headers to include in requests.
            skip_health_check: If True, skip the initial health check.
            persistence: Optional SessionPersistDriver implementation for durable
                session storage. Defaults to InMemorySessionPersistDriver().
        """
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._headers = headers or {}
        self._disposed = False
        self._transport = HttpTransport(
            base_url=self._base_url,
            token=token,
            headers=self._headers,
        )
        self._persistence: SessionPersistDriver = persistence if persistence is not None else InMemorySessionPersistDriver()
        self._active_sessions: dict[str, Session] = {}
        self._provider: SandboxProvider | None = None
        self._event_listeners: dict[str, set[Callable[[dict[str, Any]], None]]] = {}

    @property
    def inspector_url(self) -> str:
        """Get the inspector URL for this sandbox.

        Returns:
            The inspector URL for debugging and monitoring the sandbox.
        """
        return build_inspector_url(self._base_url, token=self._token, headers=self._headers)

    @property
    def sandbox_id(self) -> str | None:
        """Get the sandbox ID if using a provider.

        Returns:
            The sandbox ID if a provider is set, otherwise None.
        """
        if self._provider is None:
            return None
        return self._provider.sandbox_id

    @property
    def sandbox(self) -> SandboxProvider | None:
        """Get the sandbox provider reference.

        Returns:
            The sandbox provider if one is set, otherwise None.
        """
        return self._provider
    @classmethod
    async def connect(
        cls,
        base_url: str,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        skip_health_check: bool = False,
        health_timeout: float = 15.0,
        *,
        persistence: SessionPersistDriver | None = None,
    ) -> SandboxAgent:
        """Connect to a SandboxAgent server.

        Args:
            base_url: The base URL of the SandboxAgent server.
            token: Optional authentication token.
            headers: Optional additional headers to include in requests.
            skip_health_check: If True, skip the initial health check.
            health_timeout: Maximum time in seconds to wait for health check.
            persistence: Optional SessionPersistDriver for durable session
                storage. Defaults to InMemorySessionPersistDriver().

        Returns:
            A connected SandboxAgent instance.
        """
        agent = cls(base_url, token, headers, skip_health_check, persistence=persistence)
        if not skip_health_check:
            await agent.wait_for_health(timeout_seconds=health_timeout)
        return agent

    @classmethod
    async def start(
        cls,
        *,
        provider: SandboxProvider | None = None,
        workspace_files: dict[str, str] | None = None,
        workspace_env: dict[str, str] | None = None,
        persistence: SessionPersistDriver | None = None,
        **kwargs: Any,
    ) -> SandboxAgent:
        """Start a new sandbox agent instance.

        This method supports two modes:
        1. Local spawn (default): Spawns a local sandbox-agent binary.
        2. Provider-based: Uses a SandboxProvider to create and manage the sandbox.

        Args:
            provider: Optional SandboxProvider for provider-based startup.
            workspace_files: Optional dictionary of filename -> content to write to workspace.
            workspace_env: Optional dictionary of environment variables to inject.
            persistence: Optional SessionPersistDriver for durable session
                storage. Defaults to InMemorySessionPersistDriver(). Forwarded
                to spawn_sandbox_agent in local-spawn mode.
            **kwargs: Additional arguments. For local spawn, passed to spawn_sandbox_agent.

        Returns:
            A connected SandboxAgent instance.

        Raises:
            SandboxAgentError: If the sandbox fails to start or connect.
        """
        if provider is not None:
            # Provider-based startup
            if workspace_env:
                _merge_env_into_provider(provider, workspace_env)

            sandbox_id = await provider.create()
            base_url = await provider.get_url(sandbox_id)
            token = kwargs.get("token")
            headers = kwargs.get("headers")
            skip_health_check = kwargs.get("skip_health_check", False)
            health_timeout = kwargs.get("health_timeout", 15.0)

            agent = cls(
                base_url=base_url,
                token=token,
                headers=headers,
                skip_health_check=skip_health_check,
                persistence=persistence,
            )
            agent._provider = provider

            if not skip_health_check:
                await agent.wait_for_health(timeout_seconds=health_timeout)

            if workspace_files or workspace_env:
                await agent._bootstrap_workspace(
                    workspace_files=workspace_files,
                    workspace_env=workspace_env,
                )

            return agent

        # Local spawn mode
        from sandboxagent.spawn import spawn_sandbox_agent
        if persistence is not None:
            kwargs.setdefault("persistence", persistence)
        return await spawn_sandbox_agent(**kwargs)

    async def _bootstrap_workspace(
        self,
        workspace_files: dict[str, str] | None = None,
        workspace_env: dict[str, str] | None = None,
    ) -> None:
        """Bootstrap workspace files and environment variables.

        Creates the workspace directory and writes files and/or a .env file.
        Errors are logged as warnings but do not fail startup.

        Args:
            workspace_files: Dictionary of filename -> content to write.
            workspace_env: Dictionary of environment variables to inject.
        """
        workspace_dir = "/workspace"
        if self._provider is not None:
            cwd = self._provider.default_cwd
            if cwd is not None:
                workspace_dir = cwd

        try:
            await self.mkdir_fs(workspace_dir)
        except Exception:
            pass

        if workspace_files:
            for filename, content in workspace_files.items():
                safe_filename = os.path.basename(filename.replace("\\", "/"))
                if not safe_filename or safe_filename in {".", ".."}:
                    import warnings
                    warnings.warn(
                        f"Skipping unsafe workspace filename {filename!r}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    continue

                file_path = f"{workspace_dir}/{safe_filename}"
                try:
                    await self.write_file(file_path, content)
                except Exception as e:
                    import warnings
                    warnings.warn(
                        f"Failed to write workspace file {file_path}: {e}",
                        RuntimeWarning,
                        stacklevel=2,
                    )

        if workspace_env:
            env_lines = [f'{key}="{_escape_dotenv_value(value)}"' for key, value in workspace_env.items()]
            env_content = "\n".join(env_lines) + "\n"
            env_path = f"{workspace_dir}/.env"
            try:
                await self.write_file(env_path, env_content)
            except Exception as e:
                import warnings
                warnings.warn(
                    f"Failed to write workspace env file {env_path}: {e}",
                    RuntimeWarning,
                    stacklevel=2,
                )

    async def dispose(self) -> None:
        """Dispose of the client and close the transport."""
        self._disposed = True
        # Disconnect all active ACP sessions
        for session in list(self._active_sessions.values()):
            if session.acp_client:
                await session.acp_client.disconnect()
        self._active_sessions.clear()
        self._event_listeners.clear()
        await self._transport.close()

    async def __aenter__(self) -> SandboxAgent:
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the async context manager and dispose."""
        await self.dispose()

    async def pause_sandbox(self) -> None:
        """Pause the sandbox.

        Sends a request to pause the sandbox, which may free up resources
        while preserving the sandbox state.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no provider is associated with this client.
        """
        if self._provider is None:
            raise RuntimeError("SandboxAgent is not attached to a provisioned sandbox.")
        await self._transport.post(f"{API_PREFIX}/sandbox/pause")

    async def resume_sandbox(self) -> None:
        """Resume the sandbox.

        Sends a request to resume a paused sandbox.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no provider is associated with this client.
        """
        if self._provider is None:
            raise RuntimeError("SandboxAgent is not attached to a provisioned sandbox.")
        await self._transport.post(f"{API_PREFIX}/sandbox/resume")

    async def restart_sandbox(self) -> None:
        """Restart the sandbox.

        Sends a request to restart the sandbox.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no provider is associated with this client.
        """
        if self._provider is None:
            raise RuntimeError("SandboxAgent is not attached to a provisioned sandbox.")
        await self._transport.post(f"{API_PREFIX}/sandbox/restart")

    async def destroy_sandbox(self) -> None:
        """Destroy the sandbox.

        Permanently destroys the sandbox and releases all associated resources.
        This operation cannot be undone.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no provider is associated with this client.
        """
        if self._provider is None:
            raise RuntimeError("SandboxAgent is not attached to a provisioned sandbox.")
        try:
            await self._transport.delete(f"{API_PREFIX}/sandbox")
        finally:
            await self.dispose()
            self._provider = None

    async def kill_sandbox(self) -> None:
        """Kill the sandbox.

        Forcefully terminates the sandbox immediately.
        This is a hard stop that may not gracefully shut down processes.

        Raises:
            SandboxAgentError: If the request fails.
            RuntimeError: If no provider is associated with this client.
        """
        if self._provider is None:
            raise RuntimeError("SandboxAgent is not attached to a provisioned sandbox.")
        try:
            await self._transport.post(f"{API_PREFIX}/sandbox/kill")
        finally:
            await self.dispose()
            self._provider = None

    async def health(self) -> dict[str, Any]:
        response = await self._transport.get(f"{API_PREFIX}/health")
        return response.json()

    async def wait_for_health(self, timeout_seconds: float = 15.0) -> dict[str, Any]:
        """Wait for the server to become healthy.

        Polls the health endpoint with exponential backoff until the server
        responds successfully or the timeout is reached.

        Args:
            timeout_seconds: Maximum time to wait for health (default: 15.0).

        Returns:
            The health status response.

        Raises:
            TimeoutError: If the server does not become healthy within the timeout.
            SandboxAgentError: If the request fails.
        """
        import asyncio

        delay = HEALTH_WAIT_MIN_DELAY
        elapsed = 0.0

        while elapsed < timeout_seconds:
            try:
                return await self.health()
            except SandboxAgentError:
                if elapsed + delay >= timeout_seconds:
                    break
                await asyncio.sleep(delay)
                elapsed += delay
                delay = min(delay * 2, HEALTH_WAIT_MAX_DELAY)

        raise TimeoutError(f"Server did not become healthy within {timeout_seconds}s")

    async def read_file(self, path: str) -> str:
        """Read the contents of a file.

        Args:
            path: The path to the file.

        Returns:
            The file contents as a string.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(
            f"{API_PREFIX}/fs/file", params={"path": path}
        )
        return response.text

    async def write_file(self, path: str, content: str | bytes) -> None:
        """Write content to a file.

        Args:
            path: The path to the file.
            content: The content to write (string or bytes).

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.put(
            f"{API_PREFIX}/fs/file",
            content=content,
            params={"path": path},
        )

    async def delete_entry(self, path: str) -> None:
        """Delete a file or directory entry.

        Args:
            path: The path to the entry to delete.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.delete(
            f"{API_PREFIX}/fs/entry", params={"path": path}
        )

    async def list_entries(self, path: str) -> list[dict[str, Any]]:
        """List entries in a directory.

        Args:
            path: The path to the directory.

        Returns:
            A list of entry dictionaries.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(
            f"{API_PREFIX}/fs/entries", params={"path": path}
        )
        return response.json()

    async def stat(self, path: str) -> dict[str, Any]:
        """Get metadata about a file or directory.

        Args:
            path: The path to the file or directory.

        Returns:
            A dictionary with metadata about the entry.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(
            f"{API_PREFIX}/fs/stat", params={"path": path}
        )
        return response.json()

    async def move(self, from_path: str, to_path: str) -> None:
        """Move a file or directory from one location to another.

        Args:
            from_path: The source path.
            to_path: The destination path.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.post(
            f"{API_PREFIX}/fs/move",
            json={"from": from_path, "to": to_path},
        )

    async def mkdir_fs(self, path: str) -> dict[str, Any]:
        """Create a directory.

        Args:
            path: The path to the directory to create.

        Returns:
            The action response.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/fs/mkdir",
            json={"path": path},
        )
        return response.json()

    async def upload_fs_batch(self, files: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch upload files.

        Args:
            files: List of file objects to upload.

        Returns:
            The upload batch response.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/fs/batch",
            json={"files": files},
        )
        return response.json()
    async def list_processes(self, owner: str | None = None) -> list[dict[str, Any]]:
        """List running processes.

        Args:
            owner: Optional filter by process owner.

        Returns:
            A list of process information dictionaries.

        Raises:
            SandboxAgentError: If the request fails.
        """
        params = {}
        if owner:
            params["owner"] = owner
        response = await self._transport.get(f"{API_PREFIX}/processes", params=params)
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("processes", [])

    async def create_process(self, config: dict[str, Any]) -> dict[str, Any]:
        """Create a new process.

        Args:
            config: The process configuration.

        Returns:
            The created process information.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/processes",
            json=config,
        )
        return response.json()

    async def run_process(self, config: dict[str, Any]) -> dict[str, Any]:
        """Run a process and wait for it to complete.

        Args:
            config: The process configuration.

        Returns:
            The process result after completion.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/processes/run",
            json=config,
        )
        return response.json()

    async def clone_repo(
        self,
        url: str,
        path: str | None = None,
        token: str | None = None,
        branch: str | None = None,
        depth: int | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Clone a git repository into the sandbox.

        Args:
            url: The repository URL to clone.
            path: Optional destination path. Derived from URL basename if not provided.
            token: Optional authentication token.
            branch: Optional branch to clone.
            depth: Optional clone depth for shallow clones.
            timeout: Maximum time to wait for clone in seconds.

        Returns:
            The process result from the clone operation.

        Raises:
            GitCloneError: If the clone operation fails.
        """
        # Validate URL has no embedded credentials
        url_without_scheme = url.replace("https://", "").replace("http://", "")
        if "@" in url_without_scheme:
            raise GitCloneError("URL contains embedded credentials", category="auth")

        # Derive destination from URL basename if not provided
        if path is None:
            import urllib.parse

            parsed = urllib.parse.urlparse(url)
            basename = parsed.path.split("/")[-1]
            if basename.endswith(".git"):
                basename = basename[:-4]
            path = basename

        askpass_path: str | None = None
        try:
            if token is not None:
                # Generate random askpass script path
                askpass_path = f"/tmp/.git-askpass-{uuid.uuid4().hex}"

                # Write askpass script that echoes credentials based on prompt
                askpass_script = (
                    '#!/bin/sh\n'
                    'case "$1" in\n'
                    '  *Username*) echo "git" ;;\n'
                    '  *Password*) echo "$GIT_TOKEN" ;;\n'
                    'esac\n'
                )
                await self.write_file(askpass_path, askpass_script)

                # Set executable permissions via chmod
                await self.run_process({
                    "command": "chmod",
                    "args": ["+x", askpass_path],
                })

            # Build git clone command arguments
            args: list[str] = ["clone"]
            if branch is not None:
                args.extend(["--branch", branch, "--single-branch"])
            if depth is not None:
                args.extend(["--depth", str(depth)])
            args.append(url)
            args.append(path)

            # Prepare environment variables
            env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
            if token is not None and askpass_path is not None:
                env["GIT_ASKPASS"] = askpass_path
                env["GIT_TOKEN"] = token

            # Run git clone
            result = await self.run_process({
                "command": "git",
                "args": args,
                "env": env,
                "timeout": timeout,
            })

            # Parse exit code and stderr for errors
            exit_code = result.get("exit_code", result.get("exitCode", 0))
            if exit_code != 0:
                stderr = result.get("stderr", "")
                stderr_lower = stderr.lower()
                category = "unknown"

                if exit_code == 128:
                    if any(
                        p in stderr_lower
                        for p in [
                            "authentication failed",
                            "could not read username",
                            "could not read password",
                        ]
                    ):
                        category = "auth"
                    elif any(
                        p in stderr_lower
                        for p in ["404", "repository not found", "remote: not found"]
                    ):
                        category = "not_found"
                    elif any(
                        p in stderr_lower
                        for p in [
                            "could not resolve host",
                            "failed to connect",
                            "connection timed out",
                            "connection refused",
                            "network is unreachable",
                        ]
                    ):
                        category = "network"
                elif any(
                    p in stderr_lower
                    for p in [
                        "could not resolve host",
                        "failed to connect",
                        "connection timed out",
                        "network is unreachable",
                    ]
                ):
                    category = "network"

                # Sanitize token from error messages
                if token is not None:
                    stderr = stderr.replace(token, "[REDACTED]")

                raise GitCloneError(stderr, category=category)

            return result
        finally:
            # Always cleanup askpass script
            if askpass_path is not None:
                try:
                    await self.delete_entry(askpass_path)
                except Exception:
                    pass

    async def get_process(self, process_id: str) -> dict[str, Any]:
        """Get information about a process.

        Args:
            process_id: The ID of the process.

        Returns:
            The process information.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/processes/{process_id}")
        return response.json()

    async def stop_process(self, process_id: str, signal: str | None = None) -> None:
        """Stop a running process.

        Args:
            process_id: The ID of the process to stop.
            signal: Optional signal to send (e.g., 'SIGTERM', 'SIGKILL').

        Raises:
            SandboxAgentError: If the request fails.
        """
        params = {}
        if signal:
            params["signal"] = signal
        await self._transport.post(
            f"{API_PREFIX}/processes/{process_id}/stop",
            params=params,
        )

    async def send_input(self, process_id: str, data: str) -> None:
        """Send input to a process.

        Args:
            process_id: The ID of the process.
            data: The input data to send.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.post(
            f"{API_PREFIX}/processes/{process_id}/input",
            json={"data": data},
        )

    async def kill_process(self, process_id: str, signal: str = "SIGKILL") -> dict[str, Any]:
        """Kill a process.

        Args:
            process_id: The ID of the process to kill.
            signal: The signal to send (default: SIGKILL).

        Returns:
            The process information.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/processes/{process_id}/kill",
            json={"signal": signal},
        )
        return response.json()

    async def delete_process(self, process_id: str) -> None:
        """Delete a process.

        Args:
            process_id: The ID of the process to delete.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.delete(f"{API_PREFIX}/processes/{process_id}")

    async def resize_process_terminal(self, process_id: str, cols: int, rows: int) -> dict[str, Any]:
        """Resize a process terminal.

        Args:
            process_id: The ID of the process.
            cols: The number of columns.
            rows: The number of rows.

        Returns:
            The resize response.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/processes/{process_id}/terminal/resize",
            json={"cols": cols, "rows": rows},
        )
        return response.json()
    async def get_process_logs(
        self, process_id: str, follow: bool | None = None
    ) -> dict[str, Any]:
        """Get logs for a process.

        Args:
            process_id: The ID of the process.
            follow: If True, stream logs (not implemented in this method).

        Returns:
            The process logs.

        Raises:
            SandboxAgentError: If the request fails.
        """
        params = {}
        if follow is not None:
            params["follow"] = follow
        response = await self._transport.get(
            f"{API_PREFIX}/processes/{process_id}/logs",
            params=params,
        )
        return response.json()

    # --- Process Terminal & Log Streaming ---

    async def follow_process_logs(
        self,
        process_id: str,
        listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> ProcessLogSubscription:
        """Follow process logs via SSE streaming.

        This method establishes an SSE connection to stream process logs
        in real-time. Each log entry is passed to the listener callback.

        Args:
            process_id: The ID of the process to follow.
            listener: Optional callback function that receives each log entry.

        Returns:
            A ProcessLogSubscription that can be closed to stop following logs.

        Raises:
            SandboxAgentError: If the request fails.

        Example:
            >>> def on_log(entry):
            ...     print(f"[{entry['timestamp']}] {entry['message']}")
            >>> sub = await agent.follow_process_logs("proc-123", on_log)
            >>> # Later, to stop:
            >>> sub.close()
        """
        from sandboxagent.sse_streaming import follow_process_logs as _follow_logs

        # Use internal httpx client from transport
        http_client = self._transport._client

        return await _follow_logs(
            transport=http_client,
            base_url=self._base_url,
            process_id=process_id,
            listener=listener or (lambda x: None),
            token=self._token,
        )

    def build_process_terminal_websocket_url(self, process_id: str) -> str:
        """Build the WebSocket URL for a process terminal.

        Args:
            process_id: The ID of the process.

        Returns:
            The WebSocket URL string for connecting to the process terminal.

        Example:
            >>> ws_url = agent.build_process_terminal_websocket_url("proc-123")
            >>> print(ws_url)
            'ws://localhost:2468/v1/processes/proc-123/terminal/ws'
        """
        # Convert HTTP URL to WebSocket URL
        ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = ws_url.rstrip("/")

        # Build the terminal WebSocket URL
        path = f"{API_PREFIX}/processes/{process_id}/terminal/ws"

        # Add authentication if available
        if self._token:
            return f"{ws_url}{path}?access_token={self._token}"

        return f"{ws_url}{path}"

    async def connect_process_terminal(self, process_id: str) -> ProcessTerminalSession:
        """Connect to a process terminal via WebSocket.

        This method establishes a WebSocket connection to the process terminal,
        enabling interactive input/output with the process PTY.

        Args:
            process_id: The ID of the process to connect to.

        Returns:
            A connected ProcessTerminalSession instance.

        Raises:
            ConnectionError: If the WebSocket connection fails.
            SandboxAgentError: If the request fails.

        Example:
            >>> session = await agent.connect_process_terminal("proc-123")
            >>> session.on_data(lambda data: print(data.decode()))
            >>> session.send_input("echo hello\\n")
            >>> await session.close()
        """
        from sandboxagent.terminal import connect_process_terminal as _connect_terminal

        return await _connect_terminal(
            base_url=self._base_url,
            process_id=process_id,
            token=self._token,
        )

    async def list_agents(self) -> list[dict[str, Any]]:
        """List available agents.

        Returns:
            A list of agent information dictionaries.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/agents")
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("agents", [])
    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get information about a specific agent.

        Args:
            agent_id: The ID of the agent.

        Returns:
            The agent information.

        Raises:
            SandboxAgentError: If the request fails or the agent is not found.
        """
        response = await self._transport.get(f"{API_PREFIX}/agents/{agent_id}")
        return response.json()


    async def install_agent(
        self, agent_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Install an agent.

        Args:
            agent_id: The ID of the agent to install.
            config: The agent installation configuration.

        Returns:
            The installation result.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(
            f"{API_PREFIX}/agents/{agent_id}/install",
            json=config,
        )
        return response.json()

    async def get_mcp_config(self) -> dict[str, Any]:
        """Get global MCP server configuration.

        Returns:
            The global MCP server configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/config/mcp")
        return response.json()

    async def get_skills_config(self) -> dict[str, Any]:
        """Get global skills configuration.

        Returns:
            The global skills configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/config/skills")
        return response.json()
    async def set_mcp_config(self, config: dict[str, Any]) -> None:
        """Set global MCP server configuration.

        Args:
            config: The MCP server configuration to set.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.put(f"{API_PREFIX}/config/mcp", json=config)

    async def set_skills_config(self, config: dict[str, Any]) -> None:
        """Set global skills configuration.

        Args:
            config: The skills configuration to set.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.put(f"{API_PREFIX}/config/skills", json=config)





    async def delete_mcp_config(self) -> None:
        """Delete global MCP server configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.delete(f"{API_PREFIX}/mcp")

    async def delete_skills_config(self) -> None:
        """Delete global skills configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        await self._transport.delete(f"{API_PREFIX}/skills")

    async def get_process_config(self) -> dict[str, Any]:
        """Get global process configuration.

        Returns:
            The global process configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/processes/config")
        return response.json()

    async def set_process_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Set global process configuration.

        Args:
            config: The process configuration to set.

        Returns:
            The updated process configuration.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.post(f"{API_PREFIX}/processes/config", json=config)
        return response.json()

    async def list_acp_servers(self) -> dict[str, Any]:
        """List available ACP servers.

        Returns:
            A dictionary with ACP server information.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/acp")
        return response.json()

    async def get_acp_server(self, server_id: str) -> dict[str, Any]:
        """Get information about a specific ACP server.

        Args:
            server_id: The ID of the ACP server.

        Returns:
            The ACP server information.

        Raises:
            SandboxAgentError: If the request fails.
        """
        response = await self._transport.get(f"{API_PREFIX}/acp/{server_id}")
        return response.json()

    # --- Desktop methods (not supported) ---

    async def desktop_status(self) -> dict[str, Any]:
        """Get desktop streaming status.

        Returns:
            The desktop status response.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            response = await self._transport.get(f"{API_PREFIX}/desktop/status")
            return response.json()
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_start(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start desktop streaming.

        Args:
            config: Optional desktop configuration.

        Returns:
            The desktop start response.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            response = await self._transport.post(f"{API_PREFIX}/desktop/start", json=config or {})
            return response.json()
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_screenshot(self, format: str | None = None) -> bytes:  # noqa: A002
        """Take a desktop screenshot.

        Args:
            format: Optional image format.

        Returns:
            The screenshot image bytes.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            params = {}
            if format:
                params["format"] = format
            response = await self._transport.get(f"{API_PREFIX}/desktop/screenshot", params=params)
            return response.content
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_mouse_move(self, x: int, y: int) -> None:
        """Move the desktop mouse cursor.

        Args:
            x: X coordinate.
            y: Y coordinate.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            await self._transport.post(f"{API_PREFIX}/desktop/mouse/move", json={"x": x, "y": y})
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_mouse_click(self, button: str, clicks: int | None = None) -> None:
        """Click the desktop mouse.

        Args:
            button: The mouse button to click.
            clicks: Optional number of clicks.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            payload: dict[str, Any] = {"button": button}
            if clicks is not None:
                payload["clicks"] = clicks
            await self._transport.post(f"{API_PREFIX}/desktop/mouse/click", json=payload)
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_keyboard_type(self, text: str) -> None:
        """Type text on the desktop keyboard.

        Args:
            text: The text to type.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            await self._transport.post(f"{API_PREFIX}/desktop/keyboard/type", json={"text": text})
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    async def desktop_windows(self) -> dict[str, Any]:
        """Get desktop window information.

        Returns:
            The desktop windows response.

        Raises:
            DesktopNotSupportedError: If the server returns 501.
            SandboxAgentError: If the request fails.
        """
        try:
            response = await self._transport.get(f"{API_PREFIX}/desktop/windows")
            return response.json()
        except SandboxAgentError as e:
            if e.status == 501:
                raise DesktopNotSupportedError() from e
            raise

    # --- High-level session management (ACP) ---

    async def create_session(
        self,
        *,
        agent: str,
        server_id: str | None = None,
        mode: str | None = None,
        model: str | None = None,
        thought_level: str | None = None,
        id: str | None = None,  # noqa: A002
        session_id: str | None = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_permission_request: Callable[[PermissionRequest], PermissionResponse] | None = None,
    ) -> Session:
        """Create a new ACP session."""
        # Resolve server_id
        if not server_id:
            acp_servers = await self.list_acp_servers()
            servers = acp_servers.get("servers", acp_servers)
            if isinstance(servers, list) and servers:
                server_id = servers[0].get("id", "default")
            else:
                server_id = "default"

        # Build local session id first so dispatch closure can capture it
        local_session_id = session_id or id or str(uuid.uuid4())

        # Create ACP client with callbacks
        user_on_message = on_message

        def _dispatch_message(message: dict[str, Any]) -> None:
            if user_on_message:
                user_on_message(message)
            for listener in list(self._event_listeners.get(local_session_id, set())):
                try:
                    listener(message)
                except Exception:
                    pass

        acp_client = AcpHttpClient(
            base_url=self._base_url,
            server_id=server_id,
            agent=agent,
            token=self._token,
            headers=self._headers,
            on_message=_dispatch_message,
            on_error=on_error,
            on_close=on_close,
            on_permission_request=on_permission_request,
        )

        # Connect and initialize
        await acp_client.connect()
        await acp_client.initialize()

        # Create session via ACP. opencode (and likely other agents) require
        # `cwd` and `mcpServers` in session/new params — verified empirically
        # via direct curl probe 2026-04-26 against sandbox-agent server. The
        # SDK supplies sensible defaults; callers can override later via
        # session.set_*() methods.
        new_session_response = await acp_client.new_session({
            "agent": agent,
            "cwd": "/root",
            "mcpServers": [],
        })

        # Build session record. Server returns `sessionId` (e.g.
        # `ses_2344925c4ffetm4VhbFOJyv3Ej`); older versions returned
        # `agentSessionId` separately. Try both for compatibility.
        agent_sid = (
            new_session_response.get("sessionId")
            or new_session_response.get("agentSessionId")
            or ""
        )
        record = SessionRecord(
            id=local_session_id,
            agent=agent,
            agent_session_id=agent_sid,
            last_connection_id=server_id,
            created_at=int(time.time()),
            destroyed_at=None,
        )

        # Persist
        await self._persistence.update_session(record)

        # Create Session
        session = Session(sandbox=self, record=record, acp_client=acp_client)
        self._active_sessions[local_session_id] = session

        # Optionally set mode, model, thought_level
        agent_session_id = record.agent_session_id
        if mode and agent_session_id:
            await acp_client.set_session_mode({
                "sessionId": agent_session_id,
                "mode": mode,
            })
        if model and agent_session_id:
            # Set via REST if ACP doesn't have direct method
            await self._transport.post(
                f"{API_PREFIX}/sessions/{local_session_id}/model",
                json={"model": model},
            )
        if thought_level and agent_session_id:
            await self._transport.post(
                f"{API_PREFIX}/sessions/{local_session_id}/thought-level",
                json={"thoughtLevel": thought_level},
            )

        return session

    async def resume_session(self, session_id: str) -> Session:
        """Resume an existing session."""
        record = await self._persistence.get_session(session_id)
        if not record:
            raise RuntimeError(f"Session '{session_id}' not found")

        server_id = record.last_connection_id or "default"

        acp_client = AcpHttpClient(
            base_url=self._base_url,
            server_id=server_id,
            token=self._token,
            headers=self._headers,
        )

        def _dispatch_message(message: dict[str, Any]) -> None:
            for listener in list(self._event_listeners.get(session_id, set())):
                try:
                    listener(message)
                except Exception:
                    pass

        acp_client.on_message = _dispatch_message

        await acp_client.connect()
        await acp_client.initialize()

        if record.agent_session_id:
            await acp_client.load_session({"sessionId": record.agent_session_id})

        session = Session(sandbox=self, record=record, acp_client=acp_client)
        self._active_sessions[session_id] = session
        return session

    async def destroy_session(self, session_id: str) -> None:
        """Destroy a session."""
        session = self._active_sessions.pop(session_id, None)
        self._event_listeners.pop(session_id, None)
        if session and session.acp_client:
            await session.acp_client.disconnect()

        record = await self._persistence.get_session(session_id)
        if record:
            record.destroyed_at = int(time.time())
            await self._persistence.update_session(record)

    def on_session_event(
        self,
        session_id: str,
        listener: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        """Register a global event listener for a specific session.

        Args:
            session_id: The session ID to listen for events on.
            listener: Callback that receives event dictionaries.

        Returns:
            A function that unsubscribes the listener when called.
        """
        listeners = self._event_listeners.get(session_id, set())
        listeners.add(listener)
        self._event_listeners[session_id] = listeners

        def unsubscribe() -> None:
            listeners.discard(listener)
            if not listeners:
                self._event_listeners.pop(session_id, None)

        return unsubscribe

    async def list_sessions(self, page: int = 1, per_page: int = 10) -> dict[str, Any]:
        """List all sessions with pagination.

        Args:
            page: Page number (1-indexed).
            per_page: Number of sessions per page.

        Returns:
            Dictionary containing sessions list and pagination info.
        """
        response = await self._transport.get(
            f"{API_PREFIX}/sessions",
            params={"page": page, "perPage": per_page},
        )
        return response.json()

    async def get_session(self, session_id: str) -> SessionRecord:
        """Get a single session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The session record.

        Raises:
            SandboxAgentError: If the session is not found.
        """
        response = await self._transport.get(f"{API_PREFIX}/sessions/{session_id}")
        data = response.json()
        return SessionRecord.model_validate(data)

    async def get_events(
        self,
        session_id: str,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Get session events with pagination.

        Args:
            session_id: The session ID.
            page: Page number (1-indexed).
            per_page: Number of events per page.

        Returns:
            Dictionary containing events list and pagination info.
        """
        response = await self._transport.get(
            f"{API_PREFIX}/sessions/{session_id}/events",
            params={"page": page, "perPage": per_page},
        )
        return response.json()

    async def resume_or_create_session(
        self,
        agent: str,
        resume_token: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> Session:
        """Atomic resume or create session operation.

        First attempts to resume an existing session using the resume token.
        If the resume fails (404), creates a new session.

        Args:
            agent: The agent name.
            resume_token: Optional resume token for existing session.
            config: Optional configuration for new session.

        Returns:
            A Session object (either resumed or newly created).
        """
        if resume_token:
            try:
                return await self.resume_session(resume_token)
            except SandboxAgentError as e:
                if e.status != 404:
                    raise
                # Fall through to create new session

        # Create new session
        return await self.create_session(agent=agent, **(config or {}))
    async def set_session_mode(self, session_id: str, mode: str) -> dict[str, Any]:
        """Set the mode for a session."""
        session = self._active_sessions.get(session_id)
        if session and session.acp_client:
            return await session.acp_client.set_session_mode({
                "sessionId": session.agent_session_id,
                "mode": mode,
            })
        # Fallback to REST
        response = await self._transport.post(
            f"{API_PREFIX}/sessions/{session_id}/mode",
            json={"mode": mode},
        )
        return response.json()

    async def set_session_model(self, session_id: str, model: str) -> dict[str, Any]:
        """Set the model for a session."""
        response = await self._transport.post(
            f"{API_PREFIX}/sessions/{session_id}/model",
            json={"model": model},
        )
        return response.json()

    async def set_session_thought_level(
        self, session_id: str, thought_level: str
    ) -> dict[str, Any]:
        """Set the thought level for a session."""
        response = await self._transport.post(
            f"{API_PREFIX}/sessions/{session_id}/thought-level",
            json={"thoughtLevel": thought_level},
        )
        return response.json()

    async def set_session_config_option(
        self, session_id: str, config_id: str, value: str
    ) -> dict[str, Any]:
        """Set a config option for a session."""
        session = self._active_sessions.get(session_id)
        if session and session.acp_client:
            return await session.acp_client.set_session_config_option({
                "sessionId": session.agent_session_id,
                "configId": config_id,
                "value": value,
            })
        response = await self._transport.post(
            f"{API_PREFIX}/sessions/{session_id}/config-options",
            json={"configId": config_id, "value": value},
        )
        return response.json()

    async def get_session_config_options(self, session_id: str) -> list[dict[str, Any]]:
        """Get available config options for a session."""
        response = await self._transport.get(
            f"{API_PREFIX}/sessions/{session_id}/config-options"
        )
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("configOptions", [])

    async def get_session_modes(self, session_id: str) -> list[dict[str, Any]]:
        """Get available modes for a session."""
        response = await self._transport.get(
            f"{API_PREFIX}/sessions/{session_id}/modes"
        )
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("modes", [])

    async def respond_permission(
        self, session_id: str, permission_id: str, reply: str
    ) -> dict[str, Any]:
        """Respond to a permission request."""
        session = self._active_sessions.get(session_id)
        if not session or not session.acp_client:
            raise RuntimeError(f"Session '{session_id}' is not active")

        response_payload = {
            "jsonrpc": "2.0",
            "id": permission_id,
            "result": {"outcome": {"outcome": reply}},
        }
        await session.acp_client._send_message(response_payload)
        return {"success": True}

    async def raw_respond_permission(
        self, session_id: str, permission_id: str, reply: dict[str, Any]
    ) -> dict[str, Any]:
        """Respond to a permission request with raw payload."""
        session = self._active_sessions.get(session_id)
        if not session or not session.acp_client:
            raise RuntimeError(f"Session '{session_id}' is not active")

        response_payload = {
            "jsonrpc": "2.0",
            "id": permission_id,
            "result": reply,
        }
        await session.acp_client._send_message(response_payload)
        return {"success": True}

    def on_permission_request(
        self, session_id: str, handler: Callable[[PermissionRequest], PermissionResponse]
    ) -> Callable[[PermissionRequest], PermissionResponse]:
        """Register a permission request handler for a session."""
        session = self._active_sessions.get(session_id)
        if session:
            session.set_permission_callback(handler)
        return handler

def _clone_session_record(record: SessionRecord) -> SessionRecord:
    """Create a deep copy of a SessionRecord."""
    return copy.deepcopy(record)

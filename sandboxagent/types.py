"""Pydantic v2 models for Sandbox Agent API types.

This module contains type definitions for all schemas in the OpenAPI spec.
Auto-generated from OpenAPI spec version 0.4.2.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass

from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Alias Generator for camelCase/snake_case conversion
# =============================================================================


def to_camel(snake_str: str) -> str:
    """Convert snake_case string to camelCase.
    
    Examples:
        - created_at_ms -> createdAtMs
        - exit_code -> exitCode
        - process_id -> processId
    """
    components = snake_str.split("_")
    # First component stays lowercase, rest are title-cased
    return components[0] + "".join(x.title() for x in components[1:])


class SandboxModel(BaseModel):
    """Base model for all Sandbox Agent API types.
    
    Automatically converts between snake_case Python attributes and camelCase
    API field names using an alias generator.
    
    Usage:
        - Define fields in snake_case in Python
        - API will receive/send camelCase field names
        - Both snake_case and camelCase can be used for input validation
    """
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# =============================================================================
# Enums
# =============================================================================


class DesktopMouseButton(StrEnum):
    """Mouse button options."""

    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


class DesktopRecordingStatus(StrEnum):
    """Desktop recording status."""

    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"


class DesktopScreenshotFormat(StrEnum):
    """Screenshot image format."""

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class DesktopState(StrEnum):
    """Desktop runtime state."""

    INACTIVE = "inactive"
    INSTALL_REQUIRED = "install_required"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    FAILED = "failed"


class ErrorType(StrEnum):
    """Error type classification."""

    INVALID_REQUEST = "invalid_request"
    CONFLICT = "conflict"
    UNSUPPORTED_AGENT = "unsupported_agent"
    AGENT_NOT_INSTALLED = "agent_not_installed"
    INSTALL_FAILED = "install_failed"
    AGENT_PROCESS_EXITED = "agent_process_exited"
    TOKEN_INVALID = "token_invalid"
    PERMISSION_DENIED = "permission_denied"
    NOT_ACCEPTABLE = "not_acceptable"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    NOT_FOUND = "not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_ALREADY_EXISTS = "session_already_exists"
    MODE_NOT_SUPPORTED = "mode_not_supported"
    STREAM_ERROR = "stream_error"
    TIMEOUT = "timeout"


class FsEntryType(StrEnum):
    """Filesystem entry type."""

    FILE = "file"
    DIRECTORY = "directory"


class McpCommand(StrEnum):
    """MCP server command."""

    NPX = "npx"
    BUNX = "bunx"
    UVX = "uvx"


class McpRemoteTransport(StrEnum):
    """MCP remote transport type."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class ProcessLogsStream(StrEnum):
    """Process log stream type."""

    STDOUT = "stdout"
    STDERR = "stderr"
    COMBINED = "combined"
    PTY = "pty"


class ProcessOwner(StrEnum):
    """Process owner type."""

    USER = "user"
    DESKTOP = "desktop"
    SYSTEM = "system"


class ProcessState(StrEnum):
    """Process execution state."""

    RUNNING = "running"
    EXITED = "exited"


class ServerStatus(StrEnum):
    """Server process status."""

    RUNNING = "running"
    STOPPED = "stopped"


# =============================================================================
# ACP (Agent Communication Protocol) Models
# =============================================================================


class AcpEnvelope(SandboxModel):
    """JSON-RPC envelope for ACP communication."""

    jsonrpc: str
    id: Any | None = None
    method: str | None = None
    params: Any | None = None
    result: Any | None = None
    error: Any | None = None


class AcpPostQuery(SandboxModel):
    """Query parameters for ACP POST requests."""

    agent: str | None = None


class AcpServerInfo(SandboxModel):
    """Information about an active ACP server instance."""

    server_id: str = Field(alias="serverId")
    agent: str
    created_at_ms: int = Field(alias="createdAtMs")


class AcpServerListResponse(SandboxModel):
    """Response containing list of active ACP servers."""

    servers: list[AcpServerInfo]


# =============================================================================
# Agent Models
# =============================================================================


class AgentCapabilities(SandboxModel):
    """Agent capability flags."""

    plan_mode: bool = Field(alias="planMode")
    permissions: bool
    questions: bool
    tool_calls: bool = Field(alias="toolCalls")
    tool_results: bool = Field(alias="toolResults")
    text_messages: bool = Field(alias="textMessages")
    images: bool
    file_attachments: bool = Field(alias="fileAttachments")
    session_lifecycle: bool = Field(alias="sessionLifecycle")
    error_events: bool = Field(alias="errorEvents")
    reasoning: bool
    status: bool
    command_execution: bool = Field(alias="commandExecution")
    file_changes: bool = Field(alias="fileChanges")
    mcp_tools: bool = Field(alias="mcpTools")
    streaming_deltas: bool = Field(alias="streamingDeltas")
    item_started: bool = Field(alias="itemStarted")
    shared_process: bool = Field(alias="sharedProcess")


class AgentInfo(SandboxModel):
    """Information about an installed agent."""

    id: str
    installed: bool
    credentials_available: bool = Field(alias="credentialsAvailable")
    capabilities: AgentCapabilities
    version: str | None = None
    path: str | None = None
    config_options: list[Any] | None = Field(alias="configOptions", default=None)
    config_error: str | None = Field(alias="configError", default=None)
    server_status: ServerStatusInfo | None = Field(alias="serverStatus", default=None)


class AgentInstallArtifact(SandboxModel):
    """Artifact created during agent installation."""

    kind: str
    path: str
    source: str
    version: str | None = None


class AgentInstallRequest(SandboxModel):
    """Request to install an agent."""

    agent_version: str | None = Field(alias="agentVersion", default=None)
    agent_process_version: str | None = Field(alias="agentProcessVersion", default=None)
    reinstall: bool | None = None


class AgentInstallResponse(SandboxModel):
    """Response from agent installation."""

    already_installed: bool = Field(alias="alreadyInstalled")
    artifacts: list[AgentInstallArtifact]


class AgentListResponse(SandboxModel):
    """Response containing list of agents."""

    agents: list[AgentInfo]


# =============================================================================
# Desktop Models
# =============================================================================


class DesktopActionResponse(SandboxModel):
    """Generic desktop action response."""

    ok: bool


class DesktopClipboardQuery(TypedDict, total=False):
    """Query parameters for clipboard read."""

    selection: str | None


class DesktopClipboardResponse(SandboxModel):
    """Response containing clipboard contents."""

    text: str
    selection: str


class DesktopClipboardWriteRequest(SandboxModel):
    """Request to write to clipboard."""

    text: str
    selection: str | None = None


class DesktopDisplayInfoResponse(SandboxModel):
    """Response containing display information."""

    display: str
    resolution: DesktopResolution


class DesktopErrorInfo(SandboxModel):
    """Desktop error information."""

    code: str
    message: str


class DesktopKeyModifiers(SandboxModel):
    """Keyboard modifier keys state."""

    alt: bool | None = None
    cmd: bool | None = None
    ctrl: bool | None = None
    shift: bool | None = None


class DesktopKeyboardDownRequest(SandboxModel):
    """Request to press and hold a key."""

    key: str


class DesktopKeyboardPressRequest(SandboxModel):
    """Request to press a key or shortcut."""

    key: str
    modifiers: DesktopKeyModifiers | None = None


class DesktopKeyboardTypeRequest(SandboxModel):
    """Request to type text."""

    text: str
    delay_ms: int | None = Field(alias="delayMs", default=None)


class DesktopKeyboardUpRequest(SandboxModel):
    """Request to release a key."""

    key: str


class DesktopLaunchRequest(SandboxModel):
    """Request to launch an application."""

    app: str
    args: list[str] | None = None
    wait: bool | None = None


class DesktopLaunchResponse(SandboxModel):
    """Response from application launch."""

    process_id: str = Field(alias="processId")
    pid: int | None = None
    window_id: str | None = Field(alias="windowId", default=None)


class DesktopMouseClickRequest(SandboxModel):
    """Request to click at coordinates."""

    x: int
    y: int
    button: DesktopMouseButton | None = None
    click_count: int | None = Field(alias="clickCount", default=None)


class DesktopMouseDownRequest(SandboxModel):
    """Request to press and hold a mouse button."""

    button: DesktopMouseButton | None = None
    x: int | None = None
    y: int | None = None


class DesktopMouseDragRequest(SandboxModel):
    """Request to perform a drag gesture."""

    start_x: int = Field(alias="startX")
    start_y: int = Field(alias="startY")
    end_x: int = Field(alias="endX")
    end_y: int = Field(alias="endY")
    button: DesktopMouseButton | None = None


class DesktopMouseMoveRequest(SandboxModel):
    """Request to move the mouse cursor."""

    x: int
    y: int


class DesktopMousePositionResponse(SandboxModel):
    """Response containing mouse position."""

    x: int
    y: int
    screen: int | None = None
    window: str | None = None


class DesktopMouseScrollRequest(SandboxModel):
    """Request to scroll the mouse wheel."""

    x: int
    y: int
    delta_x: int | None = Field(alias="deltaX", default=None)
    delta_y: int | None = Field(alias="deltaY", default=None)


class DesktopMouseUpRequest(SandboxModel):
    """Request to release a mouse button."""

    button: DesktopMouseButton | None = None
    x: int | None = None
    y: int | None = None


class DesktopOpenRequest(SandboxModel):
    """Request to open a file or URL."""

    target: str


class DesktopOpenResponse(SandboxModel):
    """Response from opening a file or URL."""

    process_id: str = Field(alias="processId")
    pid: int | None = None


class DesktopProcessInfo(SandboxModel):
    """Information about a desktop process."""

    name: str
    running: bool
    pid: int | None = None
    log_path: str | None = Field(alias="logPath", default=None)


class DesktopRecordingInfo(SandboxModel):
    """Information about a desktop recording."""

    id: str
    status: DesktopRecordingStatus
    file_name: str = Field(alias="fileName")
    bytes: int
    started_at: str = Field(alias="startedAt")
    ended_at: str | None = Field(alias="endedAt", default=None)
    process_id: str | None = Field(alias="processId", default=None)


class DesktopRecordingListResponse(SandboxModel):
    """Response containing list of desktop recordings."""

    recordings: list[DesktopRecordingInfo]


class DesktopRecordingStartRequest(SandboxModel):
    """Request to start a desktop recording."""

    fps: int | None = None


class DesktopRegionScreenshotQuery(TypedDict, total=False):
    """Query parameters for region screenshot."""

    x: int
    y: int
    width: int
    height: int
    format: DesktopScreenshotFormat | None
    quality: int | None
    scale: float | None
    show_cursor: bool | None


class DesktopResolution(SandboxModel):
    """Display resolution information."""

    width: int
    height: int
    dpi: int | None = None


class DesktopScreenshotQuery(TypedDict, total=False):
    """Query parameters for screenshot."""

    format: DesktopScreenshotFormat | None
    quality: int | None
    scale: float | None
    show_cursor: bool | None


class DesktopStartRequest(SandboxModel):
    """Request to start the desktop runtime."""

    display_num: int | None = Field(alias="displayNum", default=None)
    width: int | None = None
    height: int | None = None
    dpi: int | None = None
    recording_fps: int | None = Field(alias="recordingFps", default=None)
    state_dir: str | None = Field(alias="stateDir", default=None)
    stream_audio_codec: str | None = Field(alias="streamAudioCodec", default=None)
    stream_frame_rate: int | None = Field(alias="streamFrameRate", default=None)
    stream_video_codec: str | None = Field(alias="streamVideoCodec", default=None)
    webrtc_port_range: str | None = Field(alias="webrtcPortRange", default=None)


class DesktopStatusResponse(SandboxModel):
    """Response containing desktop runtime status."""

    state: DesktopState
    display: str | None = None
    resolution: DesktopResolution | None = None
    processes: list[DesktopProcessInfo] = Field(default_factory=list)
    windows: list[DesktopWindowInfo] = Field(default_factory=list)
    missing_dependencies: list[str] = Field(alias="missingDependencies", default_factory=list)
    install_command: str | None = Field(alias="installCommand", default=None)
    last_error: DesktopErrorInfo | None = Field(alias="lastError", default=None)
    runtime_log_path: str | None = Field(alias="runtimeLogPath", default=None)
    started_at: str | None = Field(alias="startedAt", default=None)


class DesktopStreamStatusResponse(SandboxModel):
    """Response containing desktop stream status."""

    active: bool
    process_id: str | None = Field(alias="processId", default=None)
    window_id: str | None = Field(alias="windowId", default=None)


class DesktopWindowInfo(SandboxModel):
    """Information about a desktop window."""

    id: str
    title: str
    x: int
    y: int
    width: int
    height: int
    is_active: bool = Field(alias="isActive")


class DesktopWindowListResponse(SandboxModel):
    """Response containing list of desktop windows."""

    windows: list[DesktopWindowInfo]


class DesktopWindowMoveRequest(SandboxModel):
    """Request to move a window."""

    x: int
    y: int


class DesktopWindowResizeRequest(SandboxModel):
    """Request to resize a window."""

    width: int
    height: int


# =============================================================================
# Filesystem Models
# =============================================================================


class FsActionResponse(SandboxModel):
    """Generic filesystem action response."""

    path: str


class FsDeleteQuery(TypedDict, total=False):
    """Query parameters for filesystem delete."""

    path: str
    recursive: bool | None


class FsEntriesQuery(TypedDict, total=False):
    """Query parameters for listing directory entries."""

    path: str | None


class FsEntry(SandboxModel):
    """Filesystem directory entry."""

    name: str
    path: str
    entry_type: FsEntryType = Field(alias="entryType")
    size: int
    modified: str | None = None


class FsMoveRequest(SandboxModel):
    """Request to move/rename a file or directory."""

    from_path: str = Field(alias="from")
    to: str
    overwrite: bool | None = None


class FsMoveResponse(SandboxModel):
    """Response from move operation."""

    from_path: str = Field(alias="from")
    to: str


class FsPathQuery(TypedDict, total=False):
    """Query parameters requiring a path."""

    path: str


class FsStat(SandboxModel):
    """Filesystem entry metadata."""

    path: str
    entry_type: FsEntryType = Field(alias="entryType")
    size: int
    modified: str | None = None


class FsUploadBatchQuery(TypedDict, total=False):
    """Query parameters for batch upload."""

    path: str | None


class FsUploadBatchResponse(SandboxModel):
    """Response from batch upload operation."""

    paths: list[str]
    truncated: bool


class FsWriteResponse(SandboxModel):
    """Response from file write operation."""

    path: str
    bytes_written: int = Field(alias="bytesWritten")


# =============================================================================
# Health Models
# =============================================================================


class HealthResponse(SandboxModel):
    """Service health response."""

    status: str


# =============================================================================
# MCP (Model Context Protocol) Models
# =============================================================================


class McpConfigQuery(TypedDict, total=False):
    """Query parameters for MCP config."""

    directory: str
    mcp_name: str


class McpLocalServerConfig(SandboxModel):
    """Local MCP server configuration."""

    type: str = "local"
    command: McpCommand
    args: list[str] | None = None
    cwd: str | None = None
    enabled: bool | None = None
    env: dict[str, str] | None = None
    timeout_ms: int | None = Field(alias="timeoutMs", default=None)


class McpOAuthConfig(SandboxModel):
    """OAuth configuration for MCP server."""

    client_id: str = Field(alias="clientId")
    client_secret: str = Field(alias="clientSecret")
    token_url: str = Field(alias="tokenUrl")
    scopes: list[str] | None = None


class McpRemoteServerConfig(SandboxModel):
    """Remote MCP server configuration."""

    type: str = "remote"
    url: str
    transport: McpRemoteTransport | None = None
    headers: dict[str, str] | None = None
    env_headers: dict[str, str] | None = Field(alias="envHeaders", default=None)
    bearer_token_env_var: str | None = Field(alias="bearerTokenEnvVar", default=None)
    oauth: McpOAuthConfig | None = None
    enabled: bool | None = None
    timeout_ms: int | None = Field(alias="timeoutMs", default=None)


McpServerConfig = McpLocalServerConfig | McpRemoteServerConfig


# =============================================================================
# Problem Details (RFC 7807)
# =============================================================================


class ProblemDetails(SandboxModel):
    """RFC 7807 problem details for API errors."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


# =============================================================================
# Process Models
# =============================================================================


class ProcessConfig(SandboxModel):
    """Process runtime configuration."""

    max_concurrent_processes: int = Field(alias="maxConcurrentProcesses")
    default_run_timeout_ms: int = Field(alias="defaultRunTimeoutMs")
    max_run_timeout_ms: int = Field(alias="maxRunTimeoutMs")
    max_output_bytes: int = Field(alias="maxOutputBytes")
    max_log_bytes_per_process: int = Field(alias="maxLogBytesPerProcess")
    max_input_bytes_per_request: int = Field(alias="maxInputBytesPerRequest")


class ProcessCreateRequest(SandboxModel):
    """Request to create a long-lived process."""

    command: str
    args: list[str] | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    interactive: bool = False
    tty: bool = False


class ProcessInfo(SandboxModel):
    """Information about a managed process."""

    id: str
    command: str
    args: list[str]
    tty: bool
    interactive: bool
    owner: ProcessOwner
    status: ProcessState
    created_at_ms: int = Field(alias="createdAtMs")
    cwd: str | None = None
    pid: int | None = None
    exit_code: int | None = Field(alias="exitCode", default=None)
    exited_at_ms: int | None = Field(alias="exitedAtMs", default=None)


class ProcessInputRequest(SandboxModel):
    """Request to write input to a process."""

    data: str
    encoding: str | None = None


class ProcessInputResponse(SandboxModel):
    """Response from process input operation."""

    bytes_written: int = Field(alias="bytesWritten")


class ProcessListQuery(TypedDict, total=False):
    """Query parameters for listing processes."""

    owner: ProcessOwner | None


class ProcessListResponse(SandboxModel):
    """Response containing list of processes."""

    processes: list[ProcessInfo]


class ProcessLogEntry(SandboxModel):
    """Single process log entry."""

    sequence: int
    stream: ProcessLogsStream
    timestamp_ms: int = Field(alias="timestampMs")
    data: str
    encoding: str


class ProcessLogsQuery(TypedDict, total=False):
    """Query parameters for process logs."""

    stream: ProcessLogsStream | None
    tail: int | None
    follow: bool | None
    since: int | None


class ProcessLogsResponse(SandboxModel):
    """Response containing process logs."""

    process_id: str = Field(alias="processId")
    stream: ProcessLogsStream
    entries: list[ProcessLogEntry]


class ProcessRunRequest(SandboxModel):
    """Request to run a one-shot command."""

    command: str
    args: list[str] | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_ms: int | None = Field(alias="timeoutMs", default=None)
    max_output_bytes: int | None = Field(alias="maxOutputBytes", default=None)


class ProcessRunResponse(SandboxModel):
    """Response from running a one-shot command."""

    timed_out: bool = Field(alias="timedOut")
    stdout: str
    stderr: str
    stdout_truncated: bool = Field(alias="stdoutTruncated")
    stderr_truncated: bool = Field(alias="stderrTruncated")
    duration_ms: int = Field(alias="durationMs")
    exit_code: int | None = Field(alias="exitCode", default=None)


class ProcessSignalQuery(TypedDict, total=False):
    """Query parameters for process signals."""

    wait_ms: int | None


class ProcessTerminalResizeRequest(SandboxModel):
    """Request to resize a process terminal."""

    cols: int
    rows: int


class ProcessTerminalResizeResponse(SandboxModel):
    """Response from terminal resize."""

    cols: int
    rows: int


# =============================================================================
# Server Status Models
# =============================================================================


class ServerStatusInfo(SandboxModel):
    """Server process status information."""

    status: ServerStatus
    uptime_ms: int | None = Field(alias="uptimeMs", default=None)


# =============================================================================
# Skills Models
# =============================================================================


class SkillSource(SandboxModel):
    """Source configuration for skills."""

    type: str
    source: str
    ref: str | None = None
    subpath: str | None = None
    skills: list[str] | None = None


class SkillsConfig(SandboxModel):
    """Skills configuration."""

    sources: list[SkillSource]


class SkillsConfigQuery(TypedDict, total=False):
    """Query parameters for skills config."""

    directory: str
    skill_name: str


# =============================================================================
# Session/Event Models (Additional SDK Types)
# =============================================================================


class SessionRecord(SandboxModel):
    """Record of a persisted session."""

    id: str
    agent: str
    agent_session_id: str = Field(alias="agentSessionId")
    last_connection_id: str = Field(alias="lastConnectionId")
    created_at: int = Field(alias="createdAt")
    destroyed_at: int | None = Field(alias="destroyedAt", default=None)
    sandbox_id: str | None = Field(alias="sandboxId", default=None)
    session_init: dict[str, Any] | None = Field(alias="sessionInit", default=None)
    config_options: list[dict[str, Any]] | None = Field(alias="configOptions", default=None)
    modes: dict[str, Any] | None = None


class SessionEvent(SandboxModel):
    """Event in a session."""

    id: str
    event_index: int = Field(alias="eventIndex")
    session_id: str = Field(alias="sessionId")
    created_at: int = Field(alias="createdAt")
    connection_id: str = Field(alias="connectionId")
    sender: str
    payload: dict[str, Any]


class ListPageRequest(SandboxModel):
    """Request for paginated list."""

    cursor: str | None = None
    limit: int | None = None


class ListPage(SandboxModel):
    """Paginated list response."""

    items: list[Any]
    next_cursor: str | None = Field(alias="nextCursor", default=None)


class ListEventsRequest(ListPageRequest):
    """Request for listing session events."""

    session_id: str = Field(alias="sessionId")


# =============================================================================
# WebSocket Terminal Frame Types
# =============================================================================


class ProcessTerminalInputFrame(TypedDict):
    """Terminal input frame sent from client to server."""

    type: str  # "input"
    data: str
    encoding: str | None


class ProcessTerminalResizeFrame(TypedDict):
    """Terminal resize frame sent from client to server."""

    type: str  # "resize"
    cols: int
    rows: int


class ProcessTerminalCloseFrame(TypedDict):
    """Terminal close frame sent from client to server."""

    type: str  # "close"


ProcessTerminalClientFrame = ProcessTerminalInputFrame | ProcessTerminalResizeFrame | ProcessTerminalCloseFrame


class ProcessTerminalReadyFrame(SandboxModel):
    """Terminal ready frame sent from server to client."""

    type: str = "ready"
    process_id: str = Field(alias="processId")


class ProcessTerminalExitFrame(SandboxModel):
    """Terminal exit frame sent from server to client."""

    type: str = "exit"
    exit_code: int | None = Field(alias="exitCode", default=None)


class ProcessTerminalErrorFrame(SandboxModel):
    """Terminal error frame sent from server to client."""

    type: str = "error"
    message: str


ProcessTerminalServerFrame = ProcessTerminalReadyFrame | ProcessTerminalExitFrame | ProcessTerminalErrorFrame


# Type aliases for terminal status
TerminalReadyStatus = ProcessTerminalReadyFrame
TerminalExitStatus = ProcessTerminalExitFrame
TerminalErrorStatus = ProcessTerminalErrorFrame
TerminalStatusMessage = ProcessTerminalServerFrame


class TerminalResizePayload(SandboxModel):
    """Payload for terminal resize operations."""

    cols: int
    rows: int

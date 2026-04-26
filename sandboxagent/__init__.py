"""Sandbox Agent Python SDK — universal API for automatic coding agents in sandboxes."""
from sandboxagent.acp import (
    AcpHttpClient,
    AcpHttpError,
    AcpRpcError,
    AuthenticateRequest,
    AuthenticateResponse,
    CancelNotification,
    InitializeRequest,
    InitializeResponse,
    ListSessionsRequest,
    ListSessionsResponse,
    LoadSessionRequest,
    LoadSessionResponse,
    NewSessionRequest,
    NewSessionResponse,
    PermissionRequest,
    PermissionResponse,
    PromptRequest,
    PromptResponse,
    SetSessionConfigOptionRequest,
    SetSessionConfigOptionResponse,
    SetSessionModeRequest,
    SetSessionModeResponse,
)
from sandboxagent.client import (
    DesktopNotSupportedError,
    GitCloneError,
    SandboxAgent,
    SandboxDestroyedError,
    Session,
    UnsupportedPermissionReplyError,
    UnsupportedSessionCategoryError,
    UnsupportedSessionConfigOptionError,
    UnsupportedSessionValueError,
)
from sandboxagent.http import SandboxAgentError
from sandboxagent.terminal import (
    ProcessTerminalSession,
    connect_process_terminal,
)

try:
    from sandboxagent.desktop import DesktopStreamSession
except ImportError:
    DesktopStreamSession = None  # type: ignore[misc,assignment]
from sandboxagent.inspector import build_inspector_url
from sandboxagent.persistence import InMemorySessionPersistDriver, ListPage, SessionPersistDriver
from sandboxagent.live_acp import LiveAcpConnection
from sandboxagent.spawn import (
    SandboxAgentSpawnHandle,
    SandboxAgentSpawnOptions,
    spawn_sandbox_agent,
)

__all__ = [
    "AcpHttpClient",
    "AcpHttpError",
    "AcpRpcError",
    "AuthenticateRequest",
    "AuthenticateResponse",
    "CancelNotification",
    "DesktopNotSupportedError",

    "GitCloneError",

    "InMemorySessionPersistDriver",
    "ListPage",
    "LiveAcpConnection",

    "InitializeRequest",
    "InitializeResponse",
    "ListSessionsRequest",
    "ListSessionsResponse",
    "LoadSessionRequest",
    "LoadSessionResponse",
    "NewSessionRequest",
    "NewSessionResponse",
    "PermissionRequest",
    "PermissionResponse",
    "ProcessTerminalSession",
    "PromptRequest",
    "PromptResponse",
    "SandboxAgent",
    "SandboxAgentError",
    "SandboxAgentSpawnHandle",
    "SandboxAgentSpawnOptions",
    "SandboxDestroyedError",
    "Session",
    "SessionPersistDriver",
    "SetSessionConfigOptionRequest",
    "SetSessionConfigOptionResponse",
    "SetSessionModeRequest",
    "SetSessionModeResponse",
    "UnsupportedPermissionReplyError",
    "UnsupportedSessionCategoryError",
    "UnsupportedSessionConfigOptionError",
    "UnsupportedSessionValueError",
    "build_inspector_url",
    "connect_process_terminal",
    "spawn_sandbox_agent",
]

__version__ = "0.2.0"

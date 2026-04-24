"""Provider types — abstract interface for sandbox providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class SandboxProvider(ABC):
    """Abstract base class for sandbox providers.

    Each provider implements lifecycle management for a specific sandbox backend.
    Providers must implement the core methods for creating, destroying, and
    connecting to sandboxes.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name. Must match the prefix in sandbox IDs (for example "e2b")."""
        ...

    @abstractmethod
    async def create(self) -> str:
        """Provision a new sandbox and return the provider-specific ID."""
        ...

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """Permanently tear down a sandbox."""
        ...

    async def reconnect(self, sandbox_id: str) -> None:
        """Reconnect to an existing sandbox before health checks.

        Providers can use this to resume paused sandboxes or surface
        provider-specific reconnect errors.
        """
        pass

    async def pause(self, sandbox_id: str) -> None:
        """Gracefully stop or pause a sandbox without permanently deleting it.

        When not implemented, callers should fall back to `destroy()`.
        """
        pass

    async def kill(self, sandbox_id: str) -> None:
        """Permanently delete a sandbox.

        When not implemented, callers should fall back to `destroy()`.
        """
        pass

    async def get_url(self, sandbox_id: str) -> str:
        """Return the sandbox-agent base URL for this sandbox.

        Providers that cannot expose a URL should implement `get_fetch()` instead.
        """
        raise NotImplementedError("Provider must implement get_url() or get_fetch()")

    async def get_fetch(self, sandbox_id: str) -> Callable[..., Any]:
        """Return a fetch implementation that routes requests to the sandbox.

        Providers that expose a URL can implement `get_url()` instead.
        """
        raise NotImplementedError("Provider must implement get_url() or get_fetch()")

    async def get_inspector_url(self, sandbox_id: str, base_url: str | None = None) -> str:
        """Return a browser-ready Inspector URL for this sandbox.

        When not implemented, the SDK falls back to `{get_url()}/ui/`.
        """
        url = base_url or await self.get_url(sandbox_id)
        return f"{url}/ui/"

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server process is running inside the sandbox.

        Called during health-wait after consecutive failures, and before
        reconnecting to an existing sandbox. Implementations should be
        idempotent — if the server is already running, this should be a no-op.
        """
        pass

    env: dict[str, str] | None = None
    """Environment variables for the sandbox.

    Providers that support environment variable injection can set this
    attribute. When None, no extra environment variables are injected.
    """

    def set_env(self, env: dict[str, str]) -> None:
        """Set environment variables for the sandbox.

        Args:
            env: Dictionary of environment variable names to values.
        """
        self.env = env

    @property
    def default_cwd(self) -> str | None:
        """Default working directory for sessions.

        Remote providers should set this to a path that exists inside the
        sandbox (e.g., '/home/user'). When None, falls back to process.cwd().
        """
        return None

"""Daytona provider — Daytona sandbox platform."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_SANDBOX_AGENT_IMAGE, build_server_start_command

DEFAULT_AGENT_PORT = 3000
DEFAULT_PREVIEW_TTL_SECONDS = 4 * 60 * 60
DEFAULT_CWD = "/home/sandbox"


class DaytonaProviderOptions:
    """Options for the Daytona provider.

    Attributes:
        create: Overrides for sandbox creation options.
        image: Docker image to use for the sandbox.
        agent_port: Port for the sandbox-agent server.
        cwd: Default working directory.
        preview_ttl_seconds: TTL for preview URLs.
        delete_timeout_seconds: Timeout for sandbox deletion.
    """

    def __init__(
        self,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        image: str | None = None,
        agent_port: int | None = None,
        cwd: str | None = None,
        preview_ttl_seconds: int | None = None,
        delete_timeout_seconds: int | None = None,
    ) -> None:
        self.create = create
        self.image = image
        self.agent_port = agent_port
        self.cwd = cwd
        self.preview_ttl_seconds = preview_ttl_seconds
        self.delete_timeout_seconds = delete_timeout_seconds


class DaytonaProvider(SandboxProvider):
    """Provider for Daytona sandboxes."""

    def __init__(self, options: DaytonaProviderOptions | None = None) -> None:
        self.options = options or DaytonaProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT
        self.image = self.options.image or DEFAULT_SANDBOX_AGENT_IMAGE
        self.cwd = self.options.cwd or DEFAULT_CWD
        self.preview_ttl_seconds = self.options.preview_ttl_seconds or DEFAULT_PREVIEW_TTL_SECONDS

        try:
            from daytona_sdk import Daytona
            self._client = Daytona()
        except ImportError:
            raise ImportError("daytona provider requires 'daytona-sdk' package. Install with: pip install daytona-sdk")

    @property
    def name(self) -> str:
        return "daytona"

    @property
    def default_cwd(self) -> str | None:
        return self.cwd

    async def create(self) -> str:
        """Create a new Daytona sandbox."""
        create_opts = await self._resolve_create_options(self.options.create)

        if self.env:
            create_opts = {
                **create_opts,
                "envVars": {**(create_opts.get("envVars") or {}), **self.env},
            }

        sandbox = await self._client.create(
            image=self.image,
            auto_stop_interval=0,
            **create_opts,
        )

        # Start the sandbox-agent server
        await sandbox.process.execute_command(build_server_start_command(self.agent_port))

        return sandbox.id

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the Daytona sandbox."""
        sandbox = await self._client.get(sandbox_id)
        if sandbox is None:
            return
        await sandbox.delete(self.options.delete_timeout_seconds)

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the Daytona sandbox."""
        sandbox = await self._client.get(sandbox_id)
        if sandbox is None:
            raise RuntimeError(f"daytona sandbox not found: {sandbox_id}")

        preview = await sandbox.get_signed_preview_url(self.agent_port, self.preview_ttl_seconds)
        return preview if isinstance(preview, str) else preview.url

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        sandbox = await self._client.get(sandbox_id)
        if sandbox is None:
            raise RuntimeError(f"daytona sandbox not found: {sandbox_id}")
        await sandbox.process.execute_command(build_server_start_command(self.agent_port))

    async def _resolve_create_options(
        self, value: dict[str, Any] | Callable[[], dict[str, Any]] | None
    ) -> dict[str, Any]:
        """Resolve create options that may be a function or dict."""
        if value is None:
            return {}
        if callable(value):
            import inspect

            if inspect.iscoroutinefunction(value):
                return await value()
            return value()
        return value


def daytona(options: DaytonaProviderOptions | None = None) -> DaytonaProvider:
    """Create a Daytona provider instance.

    Args:
        options: Configuration options for the Daytona provider.

    Returns:
        A configured DaytonaProvider instance.
    """
    return DaytonaProvider(options)

"""Cloudflare provider — Cloudflare Workers integration."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider

DEFAULT_AGENT_PORT = 3000


class CloudflareSandboxClient:
    """Interface for Cloudflare sandbox client."""

    async def create(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a new sandbox."""
        raise NotImplementedError()

    async def connect(
        self, sandbox_id: str, options: dict[str, Any] | None = None
    ) -> "CloudflareSandboxConnection":
        """Connect to an existing sandbox."""
        raise NotImplementedError()


class CloudflareSandboxConnection:
    """Interface for Cloudflare sandbox connection."""

    async def close(self) -> None:
        """Close the connection."""
        pass

    async def stop(self) -> None:
        """Stop the sandbox."""
        pass

    async def container_fetch(
        self, input: str, init: dict[str, Any] | None = None, port: int | None = None
    ) -> Any:
        """Fetch from the container."""
        raise NotImplementedError()


class CloudflareProviderOptions:
    """Options for the Cloudflare provider.

    Attributes:
        sdk: Cloudflare sandbox client SDK.
        create: Overrides for sandbox creation options.
        agent_port: Port for the sandbox-agent server.
    """

    def __init__(
        self,
        sdk: CloudflareSandboxClient,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        agent_port: int | None = None,
    ) -> None:
        self.sdk = sdk
        self.create = create
        self.agent_port = agent_port


class CloudflareProvider(SandboxProvider):
    """Provider for Cloudflare sandboxes."""

    def __init__(self, options: CloudflareProviderOptions) -> None:
        self.options = options
        self.agent_port = options.agent_port or DEFAULT_AGENT_PORT
        self._sdk = options.sdk

    @property
    def name(self) -> str:
        return "cloudflare"

    @property
    def default_cwd(self) -> str | None:
        return "/root"

    async def create(self) -> str:
        """Create a new Cloudflare sandbox."""
        if not hasattr(self._sdk, "create") or not callable(getattr(self._sdk, "create")):
            raise RuntimeError('cloudflare provider requires a sdk with a `create()` method.')

        create_opts = await self._resolve_create_options(self.options.create)

        if self.env:
            create_opts = {
                **create_opts,
                "env": {**(create_opts.get("env") or {}), **self.env},
            }

        sandbox = await self._sdk.create(create_opts)
        sandbox_id = sandbox.get("sandbox_id") or sandbox.get("id")

        if not sandbox_id:
            raise RuntimeError("cloudflare sandbox did not return an id")

        return sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy the Cloudflare sandbox."""
        if not hasattr(self._sdk, "connect") or not callable(getattr(self._sdk, "connect")):
            raise RuntimeError('cloudflare provider requires a sdk with a `connect()` method.')

        sandbox = await self._sdk.connect(sandbox_id)

        if hasattr(sandbox, "close") and callable(getattr(sandbox, "close")):
            await sandbox.close()
            return

        if hasattr(sandbox, "stop") and callable(getattr(sandbox, "stop")):
            await sandbox.stop()

    async def get_fetch(self, sandbox_id: str) -> Callable[..., Any]:
        """Get a fetch function for the Cloudflare sandbox."""
        if not hasattr(self._sdk, "connect") or not callable(getattr(self._sdk, "connect")):
            raise RuntimeError('cloudflare provider requires a sdk with a `connect()` method.')

        sandbox = await self._sdk.connect(sandbox_id)

        async def fetch(input: str, init: dict[str, Any] | None = None) -> Any:
            init = init or {}
            # Remove signal as it's not supported
            init.pop("signal", None)
            return await sandbox.container_fetch(input, init, self.agent_port)

        return fetch

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


def cloudflare(options: CloudflareProviderOptions) -> CloudflareProvider:
    """Create a Cloudflare provider instance.

    Args:
        options: Configuration options for the Cloudflare provider.

    Returns:
        A configured CloudflareProvider instance.
    """
    return CloudflareProvider(options)

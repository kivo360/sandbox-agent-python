"""Modal provider — Modal.com sandbox integration.

Uses the modal SDK's real API surface (modal.App, modal.Sandbox,
modal.Image, modal.Secret, modal.Tunnel). Sync modal calls are wrapped
with asyncio.to_thread so the provider is safe to call from async code.

The default image is ``rivetdev/sandbox-agent:<version>-full`` which already
ships the sandbox-agent server binary — no install step needed.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_SANDBOX_AGENT_IMAGE

DEFAULT_AGENT_PORT = 3000
DEFAULT_APP_NAME = "sandbox-agent"
DEFAULT_MEMORY_MIB = 2048
DEFAULT_TIMEOUT_SECONDS = 60 * 60


class ModalProviderOptions:
    """Options for the Modal provider.

    Attributes:
        create: Per-sandbox overrides — secrets dict, encrypted_ports list,
            memory_mib, timeout. May be a dict, a callable, or an async
            callable.
        image: Docker image to use. String → ``modal.Image.from_registry``.
            ``modal.Image`` instance → used as-is.
        agent_port: Port the sandbox-agent server listens on inside the
            sandbox. Defaults to 3000.
        app_name: Modal App name (created if missing). Defaults to
            ``"sandbox-agent"``.
    """

    def __init__(
        self,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        image: str | Any | None = None,
        agent_port: int | None = None,
        app_name: str | None = None,
    ) -> None:
        self.create = create
        self.image = image
        self.agent_port = agent_port
        self.app_name = app_name


class ModalProvider(SandboxProvider):
    """Provider for Modal.com sandboxes."""

    def __init__(self, options: ModalProviderOptions | None = None) -> None:
        self.options = options or ModalProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT
        self.app_name = self.options.app_name or DEFAULT_APP_NAME

        try:
            import modal  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "modal provider requires the 'modal' package. "
                "Install with: pip install modal"
            ) from exc

    @property
    def name(self) -> str:
        return "modal"

    @property
    def default_cwd(self) -> str | None:
        return "/root"

    async def create(self) -> str:
        """Provision a Modal sandbox running sandbox-agent server.

        Returns the Modal sandbox object_id, which doubles as the sandbox_id
        the SDK uses for subsequent destroy/get_url/ensure_server calls.
        """
        import modal

        create_opts = await self._resolve_create_options(self.options.create)
        base_image = self.options.image or DEFAULT_SANDBOX_AGENT_IMAGE
        if isinstance(base_image, str):
            image = modal.Image.from_registry(base_image)
        else:
            image = base_image

        env_vars = dict(create_opts.get("secrets") or {})
        if self.env:
            env_vars = {**env_vars, **self.env}
        secrets: list = []
        if env_vars:
            secrets.append(modal.Secret.from_dict(env_vars))

        app = await asyncio.to_thread(
            modal.App.lookup, self.app_name, create_if_missing=True
        )

        extra_ports = create_opts.get("encrypted_ports") or []
        memory_mib = create_opts.get("memory_mib", DEFAULT_MEMORY_MIB)
        timeout = create_opts.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        volumes = create_opts.get("volumes") or {}

        sandbox = await asyncio.to_thread(
            lambda: modal.Sandbox.create(
                "sandbox-agent",
                "server",
                "--no-token",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.agent_port),
                app=app,
                image=image,
                secrets=secrets,
                volumes=volumes,
                encrypted_ports=[self.agent_port, *extra_ports],
                memory_mib=memory_mib,
                timeout=timeout,
            )
        )
        return sandbox.object_id

    async def destroy(self, sandbox_id: str) -> None:
        """Terminate the Modal sandbox."""
        import modal

        sandbox = modal.Sandbox.from_id(sandbox_id)
        await asyncio.to_thread(sandbox.terminate)

    async def get_url(self, sandbox_id: str) -> str:
        """Return the public tunnel URL for the sandbox-agent server port."""
        import modal

        sandbox = modal.Sandbox.from_id(sandbox_id)
        tunnels = await asyncio.to_thread(sandbox.tunnels)
        tunnel = tunnels.get(self.agent_port)
        if tunnel is None:
            raise RuntimeError(
                f"modal: no tunnel for port {self.agent_port} on sandbox {sandbox_id}"
            )
        return tunnel.url

    async def reconnect(self, sandbox_id: str) -> None:
        """Re-attach to an existing sandbox via Sandbox.from_id().

        Modal sandboxes outlive a single replica — calling from_id() in a
        new process binds to the same running sandbox without recreating it.
        """
        import modal

        await asyncio.to_thread(modal.Sandbox.from_id, sandbox_id)

    async def ensure_server(self, sandbox_id: str) -> None:
        """Restart sandbox-agent server inside an existing sandbox.

        Used when the SDK detects a stale connection and wants to recover
        without recreating the sandbox. Idempotent — if the server is
        already running, the new exec process simply duplicates it (Modal
        does not deduplicate concurrent execs).
        """
        import modal

        sandbox = modal.Sandbox.from_id(sandbox_id)
        await asyncio.to_thread(
            lambda: sandbox.exec(
                "sandbox-agent",
                "server",
                "--no-token",
                "--host",
                "0.0.0.0",
                "--port",
                str(self.agent_port),
            )
        )

    async def _resolve_create_options(
        self, value: dict[str, Any] | Callable[[], dict[str, Any]] | None
    ) -> dict[str, Any]:
        if value is None:
            return {}
        if callable(value):
            if inspect.iscoroutinefunction(value):
                return await value()
            return value()
        return value


def modal(options: ModalProviderOptions | None = None) -> ModalProvider:
    """Create a Modal provider instance.

    Args:
        options: Configuration options for the Modal provider.

    Returns:
        A configured ModalProvider instance.
    """
    return ModalProvider(options)

"""Modal provider — Modal.com serverless GPU integration."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_SANDBOX_AGENT_IMAGE

DEFAULT_AGENT_PORT = 3000
DEFAULT_APP_NAME = "sandbox-agent"
DEFAULT_MEMORY_MIB = 2048


class ModalProviderOptions:
    """Options for the Modal provider.

    Attributes:
        create: Overrides for sandbox creation options.
        image: Docker image to use (string or Modal Image object).
        agent_port: Port for the sandbox-agent server.
    """

    def __init__(
        self,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        image: str | Any | None = None,
        agent_port: int | None = None,
    ) -> None:
        self.create = create
        self.image = image
        self.agent_port = agent_port


class ModalProvider(SandboxProvider):
    """Provider for Modal.com sandboxes."""

    def __init__(self, options: ModalProviderOptions | None = None) -> None:
        self.options = options or ModalProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT

        try:
            from modal import ModalClient
            self._client = ModalClient()
        except ImportError:
            raise ImportError("modal provider requires 'modal' package. Install with: pip install modal")

    @property
    def name(self) -> str:
        return "modal"

    @property
    def default_cwd(self) -> str | None:
        return "/root"

    async def create(self) -> str:
        """Create a new Modal sandbox."""
        from modal import SandboxCreateParams

        create_opts = await self._resolve_create_options(self.options.create)
        app_name = create_opts.get("app_name", DEFAULT_APP_NAME)
        base_image = self.options.image or DEFAULT_SANDBOX_AGENT_IMAGE

        app = await self._client.apps.from_name(app_name, create_if_missing=True)

        # The default `-full` base image already includes sandbox-agent
        if isinstance(base_image, str):
            image = self._client.images.from_registry(base_image)
        else:
            image = base_image

        env_vars = create_opts.get("secrets", {})
        if self.env:
            env_vars = {**env_vars, **self.env}
        secrets = []
        if env_vars:
            secrets.append(await self._client.secrets.from_object(env_vars))

        # Extract Modal-specific options
        sandbox_create_opts = {k: v for k, v in create_opts.items() if k not in ("app_name", "secrets", "encrypted_ports")}
        extra_ports = create_opts.get("encrypted_ports", [])

        sb = await self._client.sandboxes.create(
            app,
            image,
            encrypted_ports=[self.agent_port, *extra_ports],
            secrets=secrets,
            memory_mib=sandbox_create_opts.get("memory_mib", DEFAULT_MEMORY_MIB),
            **sandbox_create_opts,
        )

        # Start the server as a long-running exec process
        sb.exec(["sandbox-agent", "server", "--no-token", "--host", "0.0.0.0", "--port", str(self.agent_port)])

        return sb.sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Terminate the Modal sandbox."""
        sb = await self._client.sandboxes.from_id(sandbox_id)
        await sb.terminate()

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the Modal sandbox."""
        sb = await self._client.sandboxes.from_id(sandbox_id)
        tunnels = await sb.tunnels()
        tunnel = tunnels.get(self.agent_port)
        if not tunnel:
            raise RuntimeError(f"modal: no tunnel found for port {self.agent_port}")
        return tunnel.url

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        sb = await self._client.sandboxes.from_id(sandbox_id)
        sb.exec(["sandbox-agent", "server", "--no-token", "--host", "0.0.0.0", "--port", str(self.agent_port)])

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


def modal(options: ModalProviderOptions | None = None) -> ModalProvider:
    """Create a Modal provider instance.

    Args:
        options: Configuration options for the Modal provider.

    Returns:
        A configured ModalProvider instance.
    """
    return ModalProvider(options)

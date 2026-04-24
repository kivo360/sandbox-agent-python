"""Docker provider — Docker-based sandboxes."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_SANDBOX_AGENT_IMAGE

DEFAULT_HOST = "127.0.0.1"
DEFAULT_AGENT_PORT = 3000


class DockerProviderOptions:
    """Options for the Docker provider.

    Attributes:
        image: Docker image to use.
        host: Host for the sandbox URL.
        agent_port: Port for the sandbox-agent server inside the container.
        env: Environment variables for the container.
        binds: Volume binds for the container.
        create_container_options: Additional options for container creation.
    """

    def __init__(
        self,
        image: str | None = None,
        host: str | None = None,
        agent_port: int | None = None,
        env: list[str] | Callable[[], list[str]] | None = None,
        binds: list[str] | Callable[[], list[str]] | None = None,
        create_container_options: dict[str, Any] | None = None,
    ) -> None:
        self.image = image
        self.host = host
        self.agent_port = agent_port
        self.env = env
        self.binds = binds
        self.create_container_options = create_container_options


class DockerProvider(SandboxProvider):
    """Provider for Docker sandboxes."""

    def __init__(self, options: DockerProviderOptions | None = None) -> None:
        self.options = options or DockerProviderOptions()
        self.image = self.options.image or DEFAULT_SANDBOX_AGENT_IMAGE
        self.host = self.options.host or DEFAULT_HOST
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT

        try:
            import docker
            self._client = docker.DockerClient(base_url="unix://var/run/docker.sock")
        except ImportError:
            raise ImportError("docker provider requires 'docker' package. Install with: pip install docker")

    @property
    def name(self) -> str:
        return "docker"

    @property
    def default_cwd(self) -> str | None:
        return "/home/sandbox"

    async def create(self) -> str:
        """Create a new Docker container."""
        import asyncio

        # Find an available host port
        host_port = await self._get_free_port()

        env = await self._resolve_value(self.options.env, [])
        if self.env:
            env = env + [f"{k}={v}" for k, v in self.env.items()]
        binds = await self._resolve_value(self.options.binds, [])

        container = self._client.containers.create(
            image=self.image,
            command=["server", "--no-token", "--host", "0.0.0.0", "--port", str(self.agent_port)],
            environment=env,
            ports={f"{self.agent_port}/tcp": ("0.0.0.0", host_port)},
            host_config={
                "auto_remove": True,
                "binds": binds,
            },
            **(self.options.create_container_options or {}),
        )

        container.start()
        return container.id

    async def destroy(self, sandbox_id: str) -> None:
        """Stop and remove the Docker container."""
        try:
            container = self._client.containers.get(sandbox_id)
            try:
                container.stop(timeout=5)
            except Exception:
                pass
            try:
                container.remove(force=True)
            except Exception:
                pass
        except Exception:
            pass

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the Docker container."""
        container = self._client.containers.get(sandbox_id)
        inspect = container.attrs
        host_port = self._extract_mapped_port(inspect, self.agent_port)
        return f"http://{self.host}:{host_port}"

    async def _resolve_value(self, value: Any, fallback: Any) -> Any:
        """Resolve a value that may be a function or static value."""
        if value is None:
            return fallback
        if callable(value):
            import inspect

            if inspect.iscoroutinefunction(value):
                return await value()
            return value()
        return value

    async def _get_free_port(self) -> int:
        """Find an available port on the host."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port

    def _extract_mapped_port(self, inspect: dict[str, Any], container_port: int) -> int:
        """Extract the host-mapped port from container inspection."""
        ports = inspect.get("NetworkSettings", {}).get("Ports", {})
        port_key = f"{container_port}/tcp"
        host_port = ports.get(port_key, [{}])[0].get("HostPort")

        if not host_port:
            raise RuntimeError(f"docker sandbox-agent port {container_port} is not published")

        return int(host_port)


def docker(options: DockerProviderOptions | None = None) -> DockerProvider:
    """Create a Docker provider instance.

    Args:
        options: Configuration options for the Docker provider.

    Returns:
        A configured DockerProvider instance.
    """
    return DockerProvider(options)

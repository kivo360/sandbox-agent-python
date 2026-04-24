"""Local provider — spawns sandbox-agent on the local machine."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sandboxagent.spawn import spawn_sandbox_agent, SandboxAgentSpawnOptions
from sandboxagent.providers.types import SandboxProvider


class LocalProviderOptions:
    """Options for the local provider.

    Attributes:
        host: Host to bind the server to. Defaults to "127.0.0.1".
        port: Port to bind the server to. If not provided, a free port is found.
        token: Authentication token. If not provided, a random token is generated.
        binary_path: Path to the sandbox-agent binary.
        log_mode: How to handle server logs. "inherit", "pipe", or "silent".
        env: Additional environment variables for the spawned process.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        binary_path: str | None = None,
        log_mode: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.binary_path = binary_path
        self.log_mode = log_mode
        self.env = env


class LocalProvider(SandboxProvider):
    """Provider for local sandbox-agent instances."""

    def __init__(self, options: LocalProviderOptions | None = None) -> None:
        self.options = options or LocalProviderOptions()
        self._sandboxes: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "local"

    async def create(self) -> str:
        """Spawn a local sandbox-agent process."""
        merged_env = {**(self.env or {}), **(self.options.env or {})}
        spawn_options: SandboxAgentSpawnOptions = {
            "host": self.options.host,
            "port": self.options.port,
            "token": self.options.token,
            "binary_path": self.options.binary_path,
            "log_mode": self.options.log_mode,
        }
        if merged_env:
            spawn_options["env"] = merged_env

        handle = await spawn_sandbox_agent(spawn_options)
        raw_sandbox_id = self._base_url_to_sandbox_id(handle.base_url)
        self._sandboxes[raw_sandbox_id] = handle
        return raw_sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Stop the local sandbox-agent process."""
        handle = self._sandboxes.pop(sandbox_id, None)
        if handle is None:
            return
        await handle.dispose()

    async def get_url(self, sandbox_id: str) -> str:
        """Return the local sandbox URL."""
        return f"http://{sandbox_id}"

    async def get_fetch(self, sandbox_id: str) -> Callable[..., Any]:
        """Return a fetch function that routes requests to the local sandbox."""
        import httpx

        handle = self._sandboxes.get(sandbox_id)
        token = self.options.token or (handle.token if handle else None)

        async def fetch(input: str, init: dict[str, Any] | None = None) -> Any:
            init = init or {}
            target_url = input.replace("http://", "").replace("https://", "")
            if not target_url.startswith("http"):
                target_url = f"http://{sandbox_id}{target_url if target_url.startswith('/') else '/' + target_url}"
            else:
                target_url = input

            headers = dict(init.get("headers", {}))
            if token and "authorization" not in headers:
                headers["authorization"] = f"Bearer {token}"

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=init.get("method", "GET"),
                    url=target_url,
                    headers=headers,
                    content=init.get("body"),
                )
                return response

        return fetch

    async def get_token(self, sandbox_id: str) -> str | None:
        """Get the authentication token for a sandbox."""
        handle = self._sandboxes.get(sandbox_id)
        return self.options.token or (handle.token if handle else None)

    @staticmethod
    def _base_url_to_sandbox_id(base_url: str) -> str:
        """Extract sandbox ID from base URL."""
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        return parsed.netloc


def local(options: LocalProviderOptions | None = None) -> LocalProvider:
    """Create a local provider instance.

    Args:
        options: Configuration options for the local provider.

    Returns:
        A configured LocalProvider instance.
    """
    return LocalProvider(options)

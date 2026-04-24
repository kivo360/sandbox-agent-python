"""Sprites provider — Sprites compute platform integration."""

from __future__ import annotations

import os
import random
import string
from typing import Any, Callable

from sandboxagent.client import SandboxDestroyedError
from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import SANDBOX_AGENT_NPX_SPEC

DEFAULT_AGENT_PORT = 8080
DEFAULT_SERVICE_NAME = "sandbox-agent"
DEFAULT_NAME_PREFIX = "sandbox-agent"
DEFAULT_SERVICE_START_DURATION = "10m"


class SpritesProviderOptions:
    """Options for the Sprites provider.

    Attributes:
        token: API token for Sprites (or env var SPRITES_API_KEY).
        client: Client configuration overrides.
        create: Overrides for sprite creation options.
        env: Environment variables for the server.
        install_agents: List of agents to install.
        agent_port: Port for the sandbox-agent server.
        service_name: Name of the service.
        service_start_duration: Duration for service start.
        name_prefix: Prefix for generated sprite names.
    """

    def __init__(
        self,
        token: str | Callable[[], str] | None = None,
        client: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        env: dict[str, str] | Callable[[], dict[str, str]] | None = None,
        install_agents: list[str] | None = None,
        agent_port: int | None = None,
        service_name: str | None = None,
        service_start_duration: str | None = None,
        name_prefix: str | None = None,
    ) -> None:
        self.token = token
        self.client = client
        self.create = create
        self.env = env
        self.install_agents = install_agents or []
        self.agent_port = agent_port
        self.service_name = service_name
        self.service_start_duration = service_start_duration
        self.name_prefix = name_prefix


class SpritesProvider(SandboxProvider):
    """Provider for Sprites compute platform."""

    def __init__(self, options: SpritesProviderOptions | None = None) -> None:
        self.options = options or SpritesProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT
        self.service_name = self.options.service_name or DEFAULT_SERVICE_NAME
        self.service_start_duration = self.options.service_start_duration or DEFAULT_SERVICE_START_DURATION
        self.name_prefix = self.options.name_prefix or DEFAULT_NAME_PREFIX

    @property
    def name(self) -> str:
        return "sprites"

    @property
    def default_cwd(self) -> str | None:
        return "/home/sprite"

    async def create(self) -> str:
        """Create a new Sprites sandbox."""
        try:
            from fly_sprites import SpritesClient
        except ImportError:
            raise ImportError("sprites provider requires 'fly-sprites' package. Install with: pip install fly-sprites")

        client = await self._get_client()
        create_options = await self._resolve_value(self.options.create, {})
        sprite_name = create_options.get("name") or self._generate_sprite_name()

        sprite = await client.create_sprite(sprite_name, create_options.get("config"))

        server_env = await self._resolve_value(self.options.env, {})
        if self.env:
            server_env = {**self.env, **server_env}

        # Install agents
        for agent in self.options.install_agents:
            await self._run_sprite_command(
                sprite, "bash", ["-lc", f"npx -y {SANDBOX_AGENT_NPX_SPEC} install-agent {agent}"], server_env
            )

        # Ensure service is running
        await self._ensure_service(client, sprite_name, server_env)

        return sprite.name

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the Sprites sandbox."""
        client = await self._get_client()
        try:
            await client.delete_sprite(sandbox_id)
        except Exception as error:
            if self._is_not_found_error(error) or "status 404" in str(error):
                return
            raise

    async def reconnect(self, sandbox_id: str) -> None:
        """Reconnect to an existing Sprites sandbox."""
        client = await self._get_client()
        try:
            await client.get_sprite(sandbox_id)
        except Exception as error:
            if self._is_not_found_error(error):
                raise SandboxDestroyedError(sandbox_id, "sprites")
            raise

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the Sprites sandbox."""
        client = await self._get_client()
        sprite = await client.get_sprite(sandbox_id)
        url = getattr(sprite, "url", None)
        if not url:
            raise RuntimeError(f"sprites API did not return a URL for sprite: {sandbox_id}")
        return url

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        client = await self._get_client()
        server_env = await self._resolve_value(self.options.env, {})
        await self._ensure_service(client, sandbox_id, server_env)

    async def get_token(self) -> str:
        """Get the API token."""
        return await self._resolve_token()

    async def _get_client(self) -> Any:
        """Get or create a SpritesClient."""
        try:
            from fly_sprites import SpritesClient
        except ImportError:
            raise ImportError("sprites provider requires 'fly-sprites' package")

        token = await self._resolve_token()
        client_options = await self._resolve_value(self.options.client, {})
        return SpritesClient(token, **client_options)

    async def _resolve_token(self) -> str:
        """Resolve the API token from options or environment."""
        token = await self._resolve_value(
            self.options.token,
            os.environ.get("SPRITES_API_KEY") or os.environ.get("SPRITE_TOKEN") or os.environ.get("SPRITES_TOKEN") or "",
        )
        if not token:
            raise RuntimeError("sprites provider requires a token. Set SPRITES_API_KEY or pass `token`.")
        return token

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

    def _generate_sprite_name(self) -> str:
        """Generate a unique sprite name."""
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{self.name_prefix}-{suffix}".lower()

    def _is_not_found_error(self, error: Exception) -> bool:
        """Check if error is a 'not found' error."""
        return isinstance(error, Exception) and str(error).startswith("Sprite not found:")

    def _shell_quote(self, value: str) -> str:
        """Quote a string for shell execution."""
        escaped = value.replace("'", "'\\''")
        return f"'{escaped}'"

    def _build_service_command(self, env: dict[str, str], port: int) -> str:
        """Build the service command."""
        export_parts = []
        for key, value in env.items():
            if not key.replace("_", "").isalnum() or key[0].isdigit():
                raise RuntimeError(f"sprites provider received an invalid environment variable name: {key}")
            export_parts.append(f"export {key}={self._shell_quote(value)}")

        export_parts.append(f"exec npx -y {SANDBOX_AGENT_NPX_SPEC} server --no-token --host 0.0.0.0 --port {port}")
        return "; ".join(export_parts)

    async def _run_sprite_command(
        self, sprite: Any, file: str, args: list[str], env: dict[str, str] | None = None
    ) -> None:
        """Run a command on a sprite."""
        try:
            from fly_sprites import ExecError
        except ImportError:
            ExecError = Exception

        try:
            result = await sprite.exec_file(file, args, env)
            if result.exit_code != 0:
                raise RuntimeError(f"sprites command failed: {file} {' '.join(args)}")
        except ExecError as error:
            raise RuntimeError(
                f"sprites command failed: {file} {' '.join(args)} (exit {error.exit_code})\n"
                f"stdout:\n{error.stdout}\nstderr:\n{error.stderr}"
            ) from error

    async def _fetch_service(self, client: Any, sprite_name: str, service_name: str) -> dict[str, Any] | None:
        """Fetch service information."""
        import httpx

        url = f"{client.base_url}/v1/sprites/{sprite_name}/services/{service_name}"
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(url, headers={"Authorization": f"Bearer {client.token}"})

        if response.status_code == 404:
            return None
        if not response.is_success:
            raise RuntimeError(f"sprites service lookup failed (status {response.status_code}): {response.text}")

        return response.json()

    async def _upsert_service(self, client: Any, sprite_name: str, service_name: str, port: int, command: str) -> None:
        """Create or update a service."""
        import httpx

        existing = await self._fetch_service(client, sprite_name, service_name)
        expected_args = ["-lc", command]
        is_current = (
            existing
            and existing.get("cmd") == "bash"
            and existing.get("http_port") == port
            and existing.get("args") == expected_args
        )
        if is_current:
            return

        url = f"{client.base_url}/v1/sprites/{sprite_name}/services/{service_name}"
        async with httpx.AsyncClient() as http_client:
            response = await http_client.put(
                url,
                headers={"Authorization": f"Bearer {client.token}", "Content-Type": "application/json"},
                json={"cmd": "bash", "args": expected_args, "http_port": port},
            )

        if not response.is_success:
            raise RuntimeError(f"sprites service upsert failed (status {response.status_code}): {response.text}")

    async def _start_service_if_needed(self, client: Any, sprite_name: str, service_name: str, duration: str) -> None:
        """Start the service if not already running."""
        import httpx

        existing = await self._fetch_service(client, sprite_name, service_name)
        status = existing.get("state", {}).get("status") if existing else None
        if status in ("running", "starting"):
            return

        url = f"{client.base_url}/v1/sprites/{sprite_name}/services/{service_name}/start?duration={duration}"
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(url, headers={"Authorization": f"Bearer {client.token}"})

        if not response.is_success:
            raise RuntimeError(f"sprites service start failed (status {response.status_code}): {response.text}")

    async def _ensure_service(self, client: Any, sprite_name: str, env: dict[str, str]) -> None:
        """Ensure the service exists and is running."""
        command = self._build_service_command(env, self.agent_port)
        await self._upsert_service(client, sprite_name, self.service_name, self.agent_port, command)
        await self._start_service_if_needed(client, sprite_name, self.service_name, self.service_start_duration)


def sprites(options: SpritesProviderOptions | None = None) -> SpritesProvider:
    """Create a Sprites provider instance.

    Args:
        options: Configuration options for the Sprites provider.

    Returns:
        A configured SpritesProvider instance.
    """
    return SpritesProvider(options)

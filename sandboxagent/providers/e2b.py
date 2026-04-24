"""E2B provider — integrates with E2B sandbox platform."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.exceptions import SandboxDestroyedError
from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import (
    DEFAULT_AGENTS,
    SANDBOX_AGENT_INSTALL_SCRIPT,
    build_server_start_command,
)

DEFAULT_AGENT_PORT = 3000
DEFAULT_TIMEOUT_MS = 3_600_000
SANDBOX_AGENT_PATH_EXPORT = 'export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"'


class E2BProviderOptions:
    """Options for the E2B provider.

    Attributes:
        create: Overrides for sandbox creation options.
        connect: Overrides for sandbox connection options.
        template: Template name or function returning template name.
        agent_port: Port for the sandbox-agent server.
        timeout_ms: Timeout for sandbox operations in milliseconds.
        auto_pause: Whether to auto-pause the sandbox when idle.
    """

    def __init__(
        self,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        connect: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
        template: str | Callable[[], str] | None = None,
        agent_port: int | None = None,
        timeout_ms: int | None = None,
        auto_pause: bool | None = None,
    ) -> None:
        self.create = create
        self.connect = connect
        self.template = template
        self.agent_port = agent_port
        self.timeout_ms = timeout_ms
        self.auto_pause = auto_pause


class E2BProvider(SandboxProvider):
    """Provider for E2B sandboxes."""

    def __init__(self, options: E2BProviderOptions | None = None) -> None:
        self.options = options or E2BProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT
        self.timeout_ms = self.options.timeout_ms or DEFAULT_TIMEOUT_MS
        self.auto_pause = self.options.auto_pause if self.options.auto_pause is not None else True

    @property
    def name(self) -> str:
        return "e2b"

    @property
    def default_cwd(self) -> str | None:
        return "/home/user"

    async def create(self) -> str:
        """Create a new E2B sandbox."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package. Install with: pip install e2b-code-interpreter")

        create_opts = await self._resolve_options(self.options.create)
        if self.env:
            create_opts["envs"] = {**self.env, **create_opts.get("envs", {})}
        template = await self._resolve_template(self.options.template)

        # Create sandbox with internet access
        if template:
            sandbox = await Sandbox.beta_create(
                template,
                allow_internet_access=True,
                **create_opts,
                timeout_ms=self.timeout_ms,
                auto_pause=self.auto_pause,
            )
        else:
            sandbox = await Sandbox.beta_create(
                allow_internet_access=True,
                **create_opts,
                timeout_ms=self.timeout_ms,
                auto_pause=self.auto_pause,
            )

        # Install sandbox-agent
        install_cmd = self._build_shell_command(
            f"curl -fsSL {SANDBOX_AGENT_INSTALL_SCRIPT} | sh", strict=True
        )
        result = await sandbox.commands.run(install_cmd)
        if result.exit_code != 0:
            raise RuntimeError(f"e2b install failed:\n{result.stderr}")

        # Install default agents
        for agent in DEFAULT_AGENTS:
            agent_cmd = self._build_shell_command(f"sandbox-agent install-agent {agent}")
            result = await sandbox.commands.run(agent_cmd)
            if result.exit_code != 0:
                raise RuntimeError(f"e2b agent install failed: {agent}\n{result.stderr}")

        # Start server in background
        server_cmd = self._build_shell_command(
            f"sandbox-agent server --no-token --host 0.0.0.0 --port {self.agent_port}"
        )
        await sandbox.commands.run(server_cmd, background=True, timeout_ms=0)

        return sandbox.sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Pause the E2B sandbox."""
        await self.pause(sandbox_id)

    async def reconnect(self, sandbox_id: str) -> None:
        """Reconnect to an existing E2B sandbox."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package")

        connect_opts = await self._resolve_options(self.options.connect, sandbox_id)
        try:
            await Sandbox.connect(sandbox_id, **connect_opts, timeout_ms=self.timeout_ms)
        except Exception as error:
            if "NotFoundError" in str(type(error)):
                raise SandboxDestroyedError(sandbox_id, "e2b")
            raise

    async def pause(self, sandbox_id: str) -> None:
        """Pause the E2B sandbox."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package")

        connect_opts = await self._resolve_options(self.options.connect, sandbox_id)
        sandbox = await Sandbox.connect(sandbox_id, **connect_opts, timeout_ms=self.timeout_ms)
        await sandbox.beta_pause()

    async def kill(self, sandbox_id: str) -> None:
        """Kill the E2B sandbox."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package")

        connect_opts = await self._resolve_options(self.options.connect, sandbox_id)
        sandbox = await Sandbox.connect(sandbox_id, **connect_opts, timeout_ms=self.timeout_ms)
        await sandbox.kill()

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the E2B sandbox."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package")

        connect_opts = await self._resolve_options(self.options.connect, sandbox_id)
        sandbox = await Sandbox.connect(sandbox_id, **connect_opts, timeout_ms=self.timeout_ms)
        return f"https://{sandbox.get_host(self.agent_port)}"

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError:
            raise ImportError("e2b provider requires 'e2b-code-interpreter' package")

        connect_opts = await self._resolve_options(self.options.connect, sandbox_id)
        sandbox = await Sandbox.connect(sandbox_id, **connect_opts, timeout_ms=self.timeout_ms)
        server_cmd = self._build_shell_command(
            f"sandbox-agent server --no-token --host 0.0.0.0 --port {self.agent_port}"
        )
        await sandbox.commands.run(server_cmd, background=True, timeout_ms=0)

    def _build_shell_command(self, command: str, strict: bool = False) -> str:
        """Build a shell command for E2B execution."""
        strict_prefix = "set -euo pipefail; " if strict else ""
        return f"bash -lc '{strict_prefix}{SANDBOX_AGENT_PATH_EXPORT}; {command}'"

    async def _resolve_options(
        self,
        value: dict[str, Any] | Callable[..., dict[str, Any]] | None,
        sandbox_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve options that may be a function or dict."""
        if value is None:
            return {}
        if callable(value):
            if sandbox_id:
                return await value(sandbox_id) if self._is_async_callable(value) else value(sandbox_id)
            return await value() if self._is_async_callable(value) else value()
        return value

    async def _resolve_template(self, value: str | Callable[[], str] | None) -> str | None:
        """Resolve template that may be a function or string."""
        if value is None:
            return None
        if callable(value):
            return await value() if self._is_async_callable(value) else value()
        return value

    def _is_async_callable(self, obj: Callable[..., Any]) -> bool:
        """Check if a callable is async."""
        import inspect

        return inspect.iscoroutinefunction(obj)


def e2b(options: E2BProviderOptions | None = None) -> E2BProvider:
    """Create an E2B provider instance.

    Args:
        options: Configuration options for the E2B provider.

    Returns:
        A configured E2BProvider instance.
    """
    return E2BProvider(options)

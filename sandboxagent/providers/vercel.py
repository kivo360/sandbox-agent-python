"""Vercel provider — Vercel sandbox integration."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_AGENTS, SANDBOX_AGENT_INSTALL_SCRIPT

DEFAULT_AGENT_PORT = 3000


class VercelProviderOptions:
    """Options for the Vercel provider.

    Attributes:
        create: Overrides for sandbox creation options.
        agent_port: Port for the sandbox-agent server.
    """

    def __init__(
        self,
        create: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
        agent_port: int | None = None,
    ) -> None:
        self.create = create
        self.agent_port = agent_port


class VercelProvider(SandboxProvider):
    """Provider for Vercel sandboxes."""

    def __init__(self, options: VercelProviderOptions | None = None) -> None:
        self.options = options or VercelProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT

    @property
    def name(self) -> str:
        return "vercel"

    @property
    def default_cwd(self) -> str | None:
        return "/home/vercel-sandbox"

    async def create(self) -> str:
        """Create a new Vercel sandbox."""
        try:
            from vercel_sandbox import Sandbox
        except ImportError:
            raise ImportError("vercel provider requires 'vercel-sandbox' package. Install with: pip install vercel-sandbox")

        create_opts = await self._resolve_create_options(self.options.create)
        create_opts["ports"] = [self.agent_port]

        if self.env:
            create_opts["env"] = {**(create_opts.get("env") or {}), **self.env}

        sandbox = await Sandbox.create(**create_opts)

        # Install sandbox-agent
        await self._run_command(
            sandbox, "sh", ["-c", f"curl -fsSL {SANDBOX_AGENT_INSTALL_SCRIPT} | sh"]
        )

        # Install default agents
        for agent in DEFAULT_AGENTS:
            await self._run_command(sandbox, "sandbox-agent", ["install-agent", agent])

        # Start server in background
        await sandbox.run_command(
            cmd="sandbox-agent",
            args=["server", "--no-token", "--host", "0.0.0.0", "--port", str(self.agent_port)],
            detached=True,
        )

        return sandbox.sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Stop the Vercel sandbox."""
        try:
            from vercel_sandbox import Sandbox
        except ImportError:
            raise ImportError("vercel provider requires 'vercel-sandbox' package")

        sandbox = await Sandbox.get(sandbox_id=sandbox_id)
        await sandbox.stop()

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the Vercel sandbox."""
        try:
            from vercel_sandbox import Sandbox
        except ImportError:
            raise ImportError("vercel provider requires 'vercel-sandbox' package")

        sandbox = await Sandbox.get(sandbox_id=sandbox_id)
        return sandbox.domain(self.agent_port)

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        try:
            from vercel_sandbox import Sandbox
        except ImportError:
            raise ImportError("vercel provider requires 'vercel-sandbox' package")

        sandbox = await Sandbox.get(sandbox_id=sandbox_id)
        await sandbox.run_command(
            cmd="sandbox-agent",
            args=["server", "--no-token", "--host", "0.0.0.0", "--port", str(self.agent_port)],
            detached=True,
        )

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

    async def _run_command(self, sandbox: Any, cmd: str, args: list[str] | None = None) -> None:
        """Run a command on the sandbox."""
        result = await sandbox.run_command(cmd=args, args=args or [])
        if result.exit_code != 0:
            stderr = await result.stderr() if hasattr(result, "stderr") else str(result)
            raise RuntimeError(f"vercel command failed: {cmd} {' '.join(args or [])}\n{stderr}")


def vercel(options: VercelProviderOptions | None = None) -> VercelProvider:
    """Create a Vercel provider instance.

    Args:
        options: Configuration options for the Vercel provider.

    Returns:
        A configured VercelProvider instance.
    """
    return VercelProvider(options)

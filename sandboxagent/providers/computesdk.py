"""ComputeSDK provider — ComputeSDK integration."""

from __future__ import annotations

from typing import Any, Callable

from sandboxagent.providers.types import SandboxProvider
from sandboxagent.providers.shared import DEFAULT_AGENTS, SANDBOX_AGENT_INSTALL_SCRIPT

DEFAULT_AGENT_PORT = 3000


class ComputeSdkProviderOptions:
    """Options for the ComputeSDK provider.

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


class ComputeSdkProvider(SandboxProvider):
    """Provider for ComputeSDK sandboxes."""

    def __init__(self, options: ComputeSdkProviderOptions | None = None) -> None:
        self.options = options or ComputeSdkProviderOptions()
        self.agent_port = self.options.agent_port or DEFAULT_AGENT_PORT

    @property
    def name(self) -> str:
        return "computesdk"

    @property
    def default_cwd(self) -> str | None:
        return "/root"

    async def create(self) -> str:
        """Create a new ComputeSDK sandbox."""
        try:
            from computesdk import compute
        except ImportError:
            raise ImportError("computesdk provider requires 'computesdk' package. Install with: pip install computesdk")

        create_opts = await self._resolve_create_options(self.options.create)

        if self.env:
            create_opts["envs"] = {**(create_opts.get("envs") or {}), **self.env}

        # Filter out empty envs
        if create_opts.get("envs") and len(create_opts["envs"]) == 0:
            create_opts.pop("envs", None)

        sandbox = await compute.sandbox.create(**create_opts)

        # Helper to run commands
        async def run(cmd: str, run_options: dict[str, Any] | None = None) -> Any:
            run_options = run_options or {}
            result = await sandbox.run_command(cmd, **run_options)
            if hasattr(result, "exit_code") and result.exit_code != 0:
                raise RuntimeError(f"computesdk command failed: {cmd} (exit {result.exit_code})\n{getattr(result, 'stderr', '')}")
            return result

        # Install sandbox-agent
        await run(f"curl -fsSL {SANDBOX_AGENT_INSTALL_SCRIPT} | sh")

        # Install default agents
        for agent in DEFAULT_AGENTS:
            await run(f"sandbox-agent install-agent {agent}")

        # Start server in background
        await run(
            f"sandbox-agent server --no-token --host 0.0.0.0 --port {self.agent_port}",
            {"background": True},
        )

        return sandbox.sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy the ComputeSDK sandbox."""
        try:
            from computesdk import compute
        except ImportError:
            raise ImportError("computesdk provider requires 'computesdk' package")

        sandbox = await compute.sandbox.get_by_id(sandbox_id)
        if sandbox:
            await sandbox.destroy()

    async def get_url(self, sandbox_id: str) -> str:
        """Get the URL for the ComputeSDK sandbox."""
        try:
            from computesdk import compute
        except ImportError:
            raise ImportError("computesdk provider requires 'computesdk' package")

        sandbox = await compute.sandbox.get_by_id(sandbox_id)
        if not sandbox:
            raise RuntimeError(f"computesdk sandbox not found: {sandbox_id}")
        return sandbox.get_url(port=self.agent_port)

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running."""
        try:
            from computesdk import compute
        except ImportError:
            raise ImportError("computesdk provider requires 'computesdk' package")

        sandbox = await compute.sandbox.get_by_id(sandbox_id)
        if not sandbox:
            raise RuntimeError(f"computesdk sandbox not found: {sandbox_id}")
        await sandbox.run_command(
            f"sandbox-agent server --no-token --host 0.0.0.0 --port {self.agent_port}",
            {"background": True},
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


def computesdk(options: ComputeSdkProviderOptions | None = None) -> ComputeSdkProvider:
    """Create a ComputeSDK provider instance.

    Args:
        options: Configuration options for the ComputeSDK provider.

    Returns:
        A configured ComputeSdkProvider instance.
    """
    return ComputeSdkProvider(options)

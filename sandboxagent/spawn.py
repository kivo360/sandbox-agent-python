"""Spawn a local sandbox-agent binary for development/testing.

This module provides functionality to spawn a local sandbox-agent server
process, find an available port, and manage the process lifecycle.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import importlib.util
import os
import platform
import secrets
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import httpx

# Platform-specific npm package names for the sandbox-agent CLI
PLATFORM_PACKAGES: dict[str, str] = {
    "darwin-arm64": "@sandbox-agent/cli-darwin-arm64",
    "darwin-x64": "@sandbox-agent/cli-darwin-x64",
    "linux-x64": "@sandbox-agent/cli-linux-x64",
    "linux-arm64": "@sandbox-agent/cli-linux-arm64",
    "win32-x64": "@sandbox-agent/cli-win32-x64",
}

DEFAULT_HEALTH_TIMEOUT = 15.0
DEFAULT_HOST = "127.0.0.1"
HEALTH_POLL_INTERVAL = 0.2
SIGTERM_WAIT_SECONDS = 5.0


class SandboxAgentSpawnOptions(TypedDict, total=False):
    """Options for spawning a sandbox-agent server.

    Attributes:
        host: Host to bind the server to. Defaults to "127.0.0.1".
        port: Port to bind the server to. If not provided, a free port is found.
        token: Authentication token. If not provided, a random token is generated.
        binary_path: Path to the sandbox-agent binary. If not provided, the binary
            is resolved via SANDBOX_AGENT_BIN env var, npm packages, or PATH.
        timeout: Maximum time in seconds to wait for the server to become healthy.
            Defaults to 15.0.
        log_mode: How to handle server logs. "inherit" passes through to parent,
            "pipe" captures output, "silent" discards output. Defaults to "inherit".
        env: Additional environment variables for the spawned process.
    """

    host: str
    port: int
    token: str
    binary_path: str
    timeout: float
    log_mode: str  # "inherit" | "pipe" | "silent"
    env: dict[str, str]


@dataclass
class SandboxAgentSpawnHandle:
    """Handle to a spawned sandbox-agent process.

    Attributes:
        base_url: The base URL of the spawned server.
        token: The authentication token for the server.
        process: The asyncio subprocess process handle.
        dispose: Async callable to clean up the spawned process.
    """

    base_url: str
    token: str
    process: asyncio.subprocess.Process
    dispose: Callable[[], Awaitable[None]]


def _get_platform_key() -> str | None:
    """Get the platform-architecture key for binary resolution."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # Normalize machine names
    if machine in ("amd64", "x86_64"):
        machine = "x64"
    elif machine in ("arm64", "aarch64"):
        machine = "arm64"

    # Windows uses 'win32' for the platform
    if system == "windows":
        system = "win32"

    key = f"{system}-{machine}"
    return key if key in PLATFORM_PACKAGES else None


def _resolve_binary_from_env() -> str | None:
    """Resolve binary path from SANDBOX_AGENT_BIN environment variable."""
    value = os.environ.get("SANDBOX_AGENT_BIN")
    if not value:
        return None

    resolved = Path(value).resolve()
    if resolved.exists():
        return str(resolved)
    return None


def _resolve_binary_from_cli_package() -> str | None:
    """Resolve binary path from platform-specific npm package."""
    platform_key = _get_platform_key()
    if not platform_key:
        return None

    pkg_name = PLATFORM_PACKAGES[platform_key]

    try:
        # Find the package using importlib
        spec = importlib.util.find_spec(pkg_name.replace("-", "_").replace("/", "."))
        if spec is None or spec.origin is None:
            # Try with the original name format
            spec = importlib.util.find_spec(pkg_name)
            if spec is None or spec.origin is None:
                return None

        pkg_dir = Path(spec.origin).parent
        bin_name = "sandbox-agent.exe" if platform.system().lower() == "windows" else "sandbox-agent"
        binary_path = pkg_dir / "bin" / bin_name

        if binary_path.exists():
            return str(binary_path)
    except Exception:
        pass

    return None


def _resolve_binary_from_path() -> str | None:
    """Resolve binary path from system PATH."""
    bin_name = "sandbox-agent.exe" if platform.system().lower() == "windows" else "sandbox-agent"

    # Use shutil.which for cross-platform PATH lookup
    binary_path = shutil.which(bin_name)
    if binary_path:
        return binary_path

    return None


def _resolve_binary(binary_path: str | None = None) -> str:
    """Resolve the sandbox-agent binary path.

    Resolution order:
    1. Explicit binary_path parameter
    2. SANDBOX_AGENT_BIN environment variable
    3. Platform-specific npm package
    4. System PATH

    Args:
        binary_path: Optional explicit path to the binary.

    Returns:
        The resolved binary path.

    Raises:
        FileNotFoundError: If the binary cannot be found.
    """
    if binary_path:
        resolved_path = Path(binary_path).resolve()
        if resolved_path.exists():
            return str(resolved_path)
        raise FileNotFoundError(f"Specified binary not found: {binary_path}")

    # Try resolution methods in order
    result: str | None = (
        _resolve_binary_from_env()
        or _resolve_binary_from_cli_package()
        or _resolve_binary_from_path()
    )

    if not result:
        raise FileNotFoundError(
            "sandbox-agent binary not found. Install @sandbox-agent/cli or set SANDBOX_AGENT_BIN."
        )

    return result


async def _find_free_port(host: str) -> int:
    """Find a free TCP port on the specified host.

    Args:
        host: The host to bind to.

    Returns:
        A free port number.
    """
    server = await asyncio.start_server(lambda r, w: None, host, 0)
    try:
        sock = server.sockets[0]
        return sock.getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()


async def _wait_for_health(
    base_url: str,
    token: str,
    timeout: float,
    process: asyncio.subprocess.Process,
) -> None:
    """Wait for the sandbox-agent server to become healthy.

    Args:
        base_url: The base URL of the server.
        token: The authentication token.
        timeout: Maximum time to wait in seconds.
        process: The subprocess process handle to check if it exited early.

    Raises:
        TimeoutError: If the server does not become healthy within the timeout.
        RuntimeError: If the process exits before becoming healthy.
    """
    start_time = asyncio.get_event_loop().time()
    last_error: str | None = None

    headers = {"Authorization": f"Bearer {token}"}

    while True:
        # Check if process exited early
        if process.returncode is not None:
            raise RuntimeError(
                f"sandbox-agent exited before becoming healthy (exit code: {process.returncode})"
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{base_url}/v1/health",
                    headers=headers,
                    timeout=1.0,
                )
                if response.status_code == 200:
                    return
                last_error = f"status {response.status_code}"
        except Exception as e:
            last_error = str(e)

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout:
            raise TimeoutError(
                f"Timed out waiting for sandbox-agent health ({last_error or 'unknown error'})"
            )

        await asyncio.sleep(HEALTH_POLL_INTERVAL)


def _register_cleanup(process: asyncio.subprocess.Process) -> Callable[[], None]:
    """Register cleanup handlers for process termination signals.

    Args:
        process: The subprocess process handle.

    Returns:
        A dispose function to unregister the cleanup handlers.
    """

    def cleanup_handler() -> None:
        if process.returncode is None:
            with contextlib.suppress(Exception):
                process.terminate()

    # Register with atexit for normal process termination
    atexit.register(cleanup_handler)

    # Note: asyncio doesn't have direct SIGINT/SIGTERM handlers like Node.js.
    # The atexit handler covers most cases. For more robust handling,
    # users should ensure they call dispose() on the handle.

    def dispose() -> None:
        atexit.unregister(cleanup_handler)

    return dispose


async def _dispose_process(
    process: asyncio.subprocess.Process,
    cleanup_unregister: Callable[[], None],
) -> None:
    """Dispose of a spawned process.

    Sends SIGTERM, waits up to 5 seconds, then sends SIGKILL if needed.

    Args:
        process: The subprocess process handle.
        cleanup_unregister: Function to unregister cleanup handlers.
    """
    # Unregister the atexit handler first
    cleanup_unregister()

    # If already exited, nothing to do
    if process.returncode is not None:
        return

    # Send SIGTERM
    process.terminate()

    # Wait up to 5 seconds for graceful shutdown
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=SIGTERM_WAIT_SECONDS)
        return

    # If still running, send SIGKILL
    if process.returncode is None:
        process.kill()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=1.0)


async def spawn_sandbox_agent(
    options: SandboxAgentSpawnOptions | None = None,
) -> SandboxAgentSpawnHandle:
    """Spawn a local sandbox-agent server process.

    This function spawns a sandbox-agent binary as a subprocess, waits for it
    to become healthy, and returns a handle for managing the process lifecycle.

    Args:
        options: Configuration options for spawning the server.

    Returns:
        A handle containing the server URL, token, process handle, and dispose function.

    Raises:
        FileNotFoundError: If the sandbox-agent binary cannot be found.
        TimeoutError: If the server does not become healthy within the timeout.
        RuntimeError: If the process exits before becoming healthy.

    Example:
        >>> handle = await spawn_sandbox_agent({
        ...     "host": "127.0.0.1",
        ...     "port": 2468,
        ...     "token": "my-secret-token",
        ... })
        >>> print(f"Server running at {handle.base_url}")
        >>> # ... use the server ...
        >>> await handle.dispose()
    """
    opts = options or {}

    # Check we're not in a browser environment
    if sys.platform == "emscripten" or "pyodide" in sys.modules:
        raise RuntimeError("Autospawn requires a native Python runtime, not a browser.")

    # Resolve configuration
    host = opts.get("host", DEFAULT_HOST)
    port = opts.get("port") or await _find_free_port(host)
    token = opts.get("token") or secrets.token_hex(24)
    timeout = opts.get("timeout", DEFAULT_HEALTH_TIMEOUT)
    log_mode = opts.get("log_mode", "inherit")
    env = opts.get("env", {})

    # Determine connect host (for 0.0.0.0 or ::, use 127.0.0.1 for connection)
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host

    # Resolve binary path
    binary = _resolve_binary(opts.get("binary_path"))

    # Prepare subprocess arguments
    args = [
        binary,
        "server",
        "--host", host,
        "--port", str(port),
        "--token", token,
    ]

    # Determine stdio configuration
    if log_mode == "inherit":
        stdin = None
        stdout = None
        stderr = None
    elif log_mode == "pipe":
        stdin = asyncio.subprocess.PIPE
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.PIPE
    else:  # silent
        stdin = asyncio.subprocess.DEVNULL
        stdout = asyncio.subprocess.DEVNULL
        stderr = asyncio.subprocess.DEVNULL

    # Prepare environment
    process_env = {**os.environ, **env}

    # Spawn the process
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=process_env,
    )

    # Register cleanup handlers
    cleanup_unregister = _register_cleanup(process)

    try:
        # Construct base URL and wait for health
        base_url = f"http://{connect_host}:{port}"
        await _wait_for_health(base_url, token, timeout, process)

        # Create dispose function
        async def dispose() -> None:
            await _dispose_process(process, cleanup_unregister)

        return SandboxAgentSpawnHandle(
            base_url=base_url,
            token=token,
            process=process,
            dispose=dispose,
        )
    except Exception:
        # Clean up on failure
        await _dispose_process(process, cleanup_unregister)
        raise

"""Shared constants and utilities for providers."""

SANDBOX_AGENT_VERSION = "0.5.0-rc.2"
DEFAULT_SANDBOX_AGENT_IMAGE = f"rivetdev/sandbox-agent:{SANDBOX_AGENT_VERSION}-full"
SANDBOX_AGENT_INSTALL_SCRIPT = f"https://releases.rivet.dev/sandbox-agent/{SANDBOX_AGENT_VERSION}/install.sh"
SANDBOX_AGENT_NPX_SPEC = f"@sandbox-agent/cli@{SANDBOX_AGENT_VERSION}"
DEFAULT_AGENTS = ["claude", "codex"]


def build_server_start_command(port: int) -> str:
    """Build a shell command to start the sandbox-agent server."""
    return f"nohup sandbox-agent server --no-token --host 0.0.0.0 --port {port} >/tmp/sandbox-agent.log 2>&1 &"

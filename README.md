# sandboxagent

Python client SDK for [Sandbox Agent](https://github.com/rivet-dev/sandbox-agent) — the universal API for automatic coding agents in sandboxes.

## Installation

```bash
pip install sandbox-agent-sdk
```

## Quick Start

```python
import asyncio
from sandboxagent import SandboxAgent

async def main():
    # Connect to a running sandbox-agent server
    agent = await SandboxAgent.connect("http://localhost:2468")
    
    # Check health
    health = await agent.health()
    print(f"Health: {health}")
    
    # Filesystem operations
    await agent.write_file("/tmp/hello.txt", "Hello from Python!")
    content = await agent.read_file("/tmp/hello.txt")
    print(f"File content: {content}")
    
    # Run a process
    result = await agent.run_process({
        "command": "/bin/echo",
        "args": ["hello", "world"],
        "cwd": "/tmp"
    })
    print(f"stdout: {result['stdout']}")
    
    # List available agents
    agents = await agent.list_agents()
    print(f"Available agents: {[a['id'] for a in agents]}")
    
    # Get inspector URL
    print(f"Inspector: {agent.inspector_url}")
    
    await agent.dispose()

asyncio.run(main())
```

## Starting a Local Server

```python
from sandboxagent import SandboxAgent

# Download and start a local sandbox-agent binary
agent = await SandboxAgent.start()
print(f"Server running at {agent._base_url}")
print(f"Inspector: {agent.inspector_url}")

# ... use the agent ...

await agent.dispose()
```

## ACP Sessions

```python
# Create an ACP session with an agent
session = await agent.create_session(agent="claude")

# Send a prompt
response = await session.prompt("Write a Python function to calculate factorial")
print(response)

# Configure session settings
await session.set_model("claude-sonnet-4-20250514")
await session.set_mode("code")

# Destroy the session
await agent.destroy_session(session.id)
```

## Workspace Configuration

Inject config files and environment variables into sandboxes during startup:

```python
from sandboxagent import SandboxAgent
from sandboxagent.workspace_config import WorkspaceConfig

# Generate config content
auth_content = WorkspaceConfig.auth_json({
    "openai_api_key": "sk-...",
    "anthropic_api_key": "sk-ant-..."
})

# Start sandbox with workspace files
agent = await SandboxAgent.start(
    workspace_files={
        "auth.json": auth_content,
        ".env": "API_KEY=secret\nDEBUG=1"
    },
    workspace_env={"FOO": "bar"}
)
```

## Git Repository Cloning

Clone git repositories at runtime or during sandbox startup:

### Runtime Cloning

Use `agent.clone_repo()` to clone repositories into a running sandbox with secure credential handling:

```python
# Public repository
result = await agent.clone_repo("https://github.com/owner/repo.git")

# Private repository with token
result = await agent.clone_repo(
    "https://github.com/owner/private.git",
    token=os.environ["GITHUB_TOKEN"],
    branch="main",
    depth=1
)
```

### Bootstrap-time Cloning

Use `WorkspaceConfig` to generate scripts for workspace startup. Repositories are cloned automatically when the sandbox starts:

```python
# Generate scripts for workspace startup
askpass = WorkspaceConfig.git_askpass_script(token)
clone_script = WorkspaceConfig.git_clone_script([
    {"url": "https://github.com/owner/repo.git", "path": "/workspace/repo"}
], token)

agent = await SandboxAgent.start(
    workspace_files={
        ".git-askpass": askpass,
        "clone.sh": clone_script
    },
    workspace_env={"GIT_TOKEN": token}
)
```

### Security Best Practices

- Use fine-grained PATs when possible
- Tokens never appear in URLs or logs
- Askpass scripts are cleaned up automatically
- Use environment variables for tokens

### Error Handling

`GitCloneError` provides categorized errors for common failure modes:

```python
from sandboxagent import GitCloneError

try:
    await agent.clone_repo("https://github.com/owner/repo.git", token="ghp_xxx")
except GitCloneError as e:
    if e.category == "auth":
        print("Authentication failed - check your token")
    elif e.category == "not_found":
        print("Repository not found")
    elif e.category == "network":
        print("Network error - check connectivity")
```

## API Coverage

### Core APIs
- **Health**: `health()`, `wait_for_health()`
- **Filesystem**: `read_file()`, `write_file()`, `list_entries()`, `stat()`, `move()`, `delete_entry()`, `mkdir_fs()`
- **Processes**: `create_process()`, `run_process()`, `list_processes()`, `get_process()`, `stop_process()`, `kill_process()`, `delete_process()`
- **Git**: `clone_repo()` — Clone repositories with secure token handling
- **Agents**: `list_agents()`, `get_agent()`, `install_agent()`
- **Config**: `get_mcp_config()`, `set_mcp_config()`, `get_skills_config()`, `set_skills_config()`, `get_process_config()`, `set_process_config()`

### Session Management
- `create_session()`, `resume_session()`, `destroy_session()`, `list_sessions()`, `get_session()`
- Session helpers: `prompt()`, `set_model()`, `set_mode()`, `set_thought_level()`, `set_config_option()`

### Process Helpers
- **Logs**: `follow_process_logs()` — SSE streaming with log subscription
- **Terminal**: `connect_process_terminal()` — WebSocket interactive terminal

### Sandbox Lifecycle
- `pause_sandbox()`, `resume_sandbox()`, `restart_sandbox()`, `destroy_sandbox()`, `kill_sandbox()`

### Workspace Configuration Helpers
- `WorkspaceConfig.auth_json()` — Generate auth.json content
- `WorkspaceConfig.git_askpass_script()` — Generate GIT_ASKPASS script
- `WorkspaceConfig.git_clone_script()` — Generate multi-repo clone script
- `WorkspaceConfig.oh_my_openagent_config()` — Generate oh-my-openagent.jsonc
- `WorkspaceConfig.opencode_config()` — Generate opencode.json

## Development

```bash
# Setup
uv sync

# Run tests
uv run pytest

# Run integration tests (requires local server)
uv run pytest -m integration

# Lint and format
uv run ruff check
uv run ruff format

# Type check
uv run mypy sandboxagent
```

## License

Apache-2.0

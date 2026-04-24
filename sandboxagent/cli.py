"""CLI for sandboxagent — start servers, run commands, inspect sandboxes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sandboxagent import SandboxAgent


async def cmd_start(args: argparse.Namespace) -> int:
    """Start a local sandbox-agent server."""
    agent = await SandboxAgent.start()
    print(f"Server running at {agent._base_url}")
    print(f"Inspector: {agent.inspector_url}")
    if args.wait:
        print("Press Ctrl+C to stop...")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
    await agent.dispose()
    return 0


async def cmd_health(args: argparse.Namespace) -> int:
    """Check server health."""
    agent = await SandboxAgent.connect(args.url)
    health = await agent.health()
    print(json.dumps(health, indent=2))
    await agent.dispose()
    return 0


async def cmd_agents(args: argparse.Namespace) -> int:
    """List available agents."""
    agent = await SandboxAgent.connect(args.url)
    agents = await agent.list_agents()
    for a in agents:
        print(f"{a['id']}: installed={a.get('installed', False)}")
    await agent.dispose()
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    """Run a command in the sandbox."""
    agent = await SandboxAgent.connect(args.url)
    result = await agent.run_process({
        "command": args.command[0],
        "args": args.command[1:],
        "cwd": args.cwd,
    })
    print(result.get("stdout", ""), end="")
    if result.get("stderr"):
        print(result["stderr"], end="", file=sys.stderr)
    await agent.dispose()
    return result.get("exitCode", 0)


async def cmd_read(args: argparse.Namespace) -> int:
    """Read a file from the sandbox."""
    agent = await SandboxAgent.connect(args.url)
    content = await agent.read_file(args.path)
    print(content)
    await agent.dispose()
    return 0


async def cmd_write(args: argparse.Namespace) -> int:
    """Write a file to the sandbox."""
    agent = await SandboxAgent.connect(args.url)
    content = sys.stdin.read() if args.stdin else args.content
    await agent.write_file(args.path, content)
    await agent.dispose()
    return 0


async def cmd_ls(args: argparse.Namespace) -> int:
    """List directory entries."""
    agent = await SandboxAgent.connect(args.url)
    entries = await agent.list_entries(args.path)
    for e in entries:
        entry_type = e.get("entryType", "file")
        size = e.get("size", 0)
        name = e.get("name", "unknown")
        print(f"{entry_type:10} {size:10} {name}")
    await agent.dispose()
    return 0


async def cmd_inspector(args: argparse.Namespace) -> int:
    """Print the inspector URL."""
    agent = await SandboxAgent.connect(args.url)
    print(agent.inspector_url)
    await agent.dispose()
    return 0


def main() -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="sandboxagent",
        description="CLI for Sandbox Agent",
    )
    parser.add_argument("--url", default="http://localhost:2468", help="Server URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    start_parser = subparsers.add_parser("start", help="Start a local server")
    start_parser.add_argument("--wait", action="store_true", help="Wait for Ctrl+C")
    start_parser.set_defaults(func=cmd_start)

    # health
    health_parser = subparsers.add_parser("health", help="Check server health")
    health_parser.set_defaults(func=cmd_health)

    # agents
    agents_parser = subparsers.add_parser("agents", help="List available agents")
    agents_parser.set_defaults(func=cmd_agents)

    # run
    run_parser = subparsers.add_parser("run", help="Run a command")
    run_parser.add_argument("command", nargs="+", help="Command and arguments")
    run_parser.add_argument("--cwd", default="/tmp", help="Working directory")
    run_parser.set_defaults(func=cmd_run)

    # read
    read_parser = subparsers.add_parser("read", help="Read a file")
    read_parser.add_argument("path", help="File path")
    read_parser.set_defaults(func=cmd_read)

    # write
    write_parser = subparsers.add_parser("write", help="Write a file")
    write_parser.add_argument("path", help="File path")
    write_parser.add_argument("content", nargs="?", help="File content")
    write_parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    write_parser.set_defaults(func=cmd_write)

    # ls
    ls_parser = subparsers.add_parser("ls", help="List directory")
    ls_parser.add_argument("path", nargs="?", default="/", help="Directory path")
    ls_parser.set_defaults(func=cmd_ls)

    # inspector
    inspector_parser = subparsers.add_parser("inspector", help="Print inspector URL")
    inspector_parser.set_defaults(func=cmd_inspector)

    args = parser.parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

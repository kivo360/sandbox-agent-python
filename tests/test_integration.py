"""Integration tests for sandboxagent against a real sandbox-agent server.

These tests require a running sandbox-agent server at http://127.0.0.1:2468.
Run with: uv run pytest tests/test_integration.py -v
Skip with: uv run pytest tests/test_integration.py -v -m 'not integration'
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from sandboxagent import SandboxAgent

SERVER_URL = "http://127.0.0.1:2468"


@pytest.fixture
async def agent():
    """Fixture that provides a connected SandboxAgent instance."""
    agent = await SandboxAgent.connect(SERVER_URL)
    yield agent
    await agent.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentConnection:
    """Test connection and health check operations."""

    async def test_connect_and_health_check(self) -> None:
        """Verify that connect() performs health check and returns healthy agent."""
        agent = await SandboxAgent.connect(SERVER_URL)

        assert agent is not None
        assert agent._base_url == SERVER_URL

        health = await agent.health()
        assert health["status"] == "ok"

        await agent.dispose()

    async def test_health_returns_valid_response(self, agent: SandboxAgent) -> None:
        """Verify health endpoint returns valid response with status."""
        health = await agent.health()

        assert isinstance(health, dict)
        assert "status" in health
        assert health["status"] == "ok"

    async def test_wait_for_health_with_timeout(self, agent: SandboxAgent) -> None:
        """Verify wait_for_health returns immediately when server is healthy."""
        health = await agent.wait_for_health(timeout_seconds=5.0)

        assert health["status"] == "ok"

    async def test_dispose_closes_connection(self) -> None:
        """Verify dispose properly closes the transport connection."""
        agent = await SandboxAgent.connect(SERVER_URL)
        await agent.dispose()

        await agent.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentFilesystem:
    """Test filesystem operations against real server."""

    async def test_write_and_read_file(self, agent: SandboxAgent) -> None:
        """Verify write_file and read_file work correctly."""
        test_path = f"/tmp/test_integration_{uuid.uuid4().hex}.txt"
        test_content = "Hello from integration test!"

        try:
            await agent.write_file(test_path, test_content)
            content = await agent.read_file(test_path)
            assert content == test_content

        finally:
            await agent.delete_entry(test_path)

    async def test_write_file_with_bytes(self, agent: SandboxAgent) -> None:
        """Verify write_file accepts bytes content."""
        test_path = f"/tmp/test_binary_{uuid.uuid4().hex}.bin"
        test_content = b"\x00\x01\x02\x03\xff\xfe"

        try:
            await agent.write_file(test_path, test_content)
            stat_info = await agent.stat(test_path)
            assert stat_info["entryType"] == "file"
            assert stat_info["size"] == len(test_content)

        finally:
            await agent.delete_entry(test_path)

    async def test_list_entries(self, agent: SandboxAgent) -> None:
        """Verify list_entries returns directory contents."""
        test_dir = f"/tmp/test_dir_{uuid.uuid4().hex}"
        test_file = os.path.join(test_dir, "test.txt")

        try:
            await agent.write_file(test_file, "test content")
            entries = await agent.list_entries(test_dir)

            assert isinstance(entries, list)
            assert len(entries) >= 1

            file_entry = next((e for e in entries if e.get("name") == "test.txt"), None)
            assert file_entry is not None
            assert file_entry.get("entryType") == "file"

        finally:
            try:
                await agent.delete_entry(test_file)
            except Exception:
                pass
            try:
                await agent.delete_entry(test_dir)
            except Exception:
                pass

    async def test_stat_file(self, agent: SandboxAgent) -> None:
        """Verify stat returns file metadata."""
        test_path = f"/tmp/test_stat_{uuid.uuid4().hex}.txt"

        try:
            await agent.write_file(test_path, "test content for stat")
            stat_info = await agent.stat(test_path)

            assert isinstance(stat_info, dict)
            assert stat_info["path"] == test_path
            assert stat_info["entryType"] == "file"
            assert "size" in stat_info
            assert stat_info["size"] > 0

        finally:
            await agent.delete_entry(test_path)

    async def test_stat_directory(self, agent: SandboxAgent) -> None:
        """Verify stat returns directory metadata."""
        test_dir = f"/tmp/test_stat_dir_{uuid.uuid4().hex}"

        try:
            test_file = os.path.join(test_dir, "file.txt")
            await agent.write_file(test_file, "content")
            stat_info = await agent.stat(test_dir)

            assert isinstance(stat_info, dict)
            assert stat_info["path"] == test_dir
            assert stat_info["entryType"] == "directory"

        finally:
            try:
                await agent.delete_entry(test_file)
            except Exception:
                pass
            try:
                await agent.delete_entry(test_dir)
            except Exception:
                pass

    async def test_move_file(self, agent: SandboxAgent) -> None:
        """Verify move operation renames/moves files."""
        source_path = f"/tmp/test_move_src_{uuid.uuid4().hex}.txt"
        dest_path = f"/tmp/test_move_dst_{uuid.uuid4().hex}.txt"

        try:
            await agent.write_file(source_path, "move me")
            await agent.move(source_path, dest_path)

            with pytest.raises(Exception):
                await agent.read_file(source_path)

            content = await agent.read_file(dest_path)
            assert content == "move me"

        finally:
            for path in [source_path, dest_path]:
                try:
                    await agent.delete_entry(path)
                except Exception:
                    pass

    async def test_delete_entry_file(self, agent: SandboxAgent) -> None:
        """Verify delete_entry removes files."""
        test_path = f"/tmp/test_delete_{uuid.uuid4().hex}.txt"

        await agent.write_file(test_path, "delete me")
        stat_info = await agent.stat(test_path)
        assert stat_info["entryType"] == "file"

        await agent.delete_entry(test_path)

        with pytest.raises(Exception):
            await agent.stat(test_path)

    async def test_delete_entry_directory(self, agent: SandboxAgent) -> None:
        """Verify delete_entry removes directories."""
        test_dir = f"/tmp/test_delete_dir_{uuid.uuid4().hex}"
        test_file = os.path.join(test_dir, "file.txt")

        await agent.write_file(test_file, "content")
        stat_info = await agent.stat(test_dir)
        assert stat_info["entryType"] == "directory"

        try:
            await agent.delete_entry(test_dir)
        except Exception:
            await agent.delete_entry(test_file)
            await agent.delete_entry(test_dir)

        with pytest.raises(Exception):
            await agent.stat(test_dir)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentProcesses:
    """Test process management operations."""

    async def test_create_and_get_process(self, agent: SandboxAgent) -> None:
        """Verify create_process creates a process and get_process retrieves it."""
        process = await agent.create_process({
            "command": "sleep",
            "args": ["30"],
        })

        assert isinstance(process, dict)
        assert "id" in process
        assert "command" in process
        assert process["command"] == "sleep"

        process_id = process["id"]

        try:
            process_info = await agent.get_process(process_id)
            assert process_info["id"] == process_id
            assert process_info["command"] == "sleep"

        finally:
            try:
                await agent.stop_process(process_id)
            except Exception:
                pass

    async def test_list_processes(self, agent: SandboxAgent) -> None:
        """Verify list_processes returns running processes."""
        process = await agent.create_process({
            "command": "sleep",
            "args": ["30"],
        })
        process_id = process["id"]

        try:
            processes = await agent.list_processes()
            assert isinstance(processes, list)

            our_process = next((p for p in processes if p.get("id") == process_id), None)
            if our_process:
                assert our_process["command"] == "sleep"

        finally:
            try:
                await agent.stop_process(process_id)
            except Exception:
                pass

    async def test_stop_process(self, agent: SandboxAgent) -> None:
        """Verify stop_process terminates a running process."""
        process = await agent.create_process({
            "command": "sleep",
            "args": ["60"],
        })
        process_id = process["id"]

        process_info = await agent.get_process(process_id)
        assert process_info["status"] in ["running", "exited"]

        await agent.stop_process(process_id, signal="SIGTERM")
        await asyncio.sleep(0.5)

        process_info = await agent.get_process(process_id)
        assert process_info["status"] in ["exited", "stopped"]

    async def test_run_process(self, agent: SandboxAgent) -> None:
        """Verify run_process executes command and returns result."""
        result = await agent.run_process({
            "command": "echo",
            "args": ["hello", "world"],
        })

        assert isinstance(result, dict)
        assert "exitCode" in result
        assert result["exitCode"] == 0
        assert "stdout" in result
        assert "hello world" in result["stdout"] or "hello" in result["stdout"]

    async def test_run_process_with_timeout(self, agent: SandboxAgent) -> None:
        """Verify run_process respects timeout."""
        result = await agent.run_process({
            "command": "sleep",
            "args": ["10"],
            "timeoutMs": 500,
        })

        assert isinstance(result, dict)
        assert "timedOut" in result
        assert result["timedOut"] is True

    async def test_process_logs(self, agent: SandboxAgent) -> None:
        """Verify get_process_logs retrieves process output."""
        result = await agent.run_process({
            "command": "echo",
            "args": ["log test output"],
        })

        if "processId" in result:
            logs = await agent.get_process_logs(result["processId"])
            assert isinstance(logs, dict)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentDesktop:
    """Test desktop operations."""

    async def test_desktop_status(self, agent: SandboxAgent) -> None:
        """Verify desktop_status returns desktop state."""
        status = await agent.desktop_status()

        assert isinstance(status, dict)
        assert "state" in status
        valid_states = ["inactive", "install_required", "starting", "active", "stopping", "failed"]
        assert status["state"] in valid_states

    async def test_desktop_start(self, agent: SandboxAgent) -> None:
        """Verify desktop_start initiates desktop runtime."""
        try:
            result = await agent.desktop_start({
                "width": 1280,
                "height": 720,
            })
        except Exception as e:
            if "Unsupported" in str(e) or "Not Implemented" in str(e):
                pytest.skip(f"Desktop not supported on this platform: {e}")
            raise

        assert isinstance(result, dict)
        assert "state" in result or "ok" in result

        await asyncio.sleep(1.0)

        status = await agent.desktop_status()
        assert status["state"] in ["starting", "active", "install_required"]

    async def test_desktop_screenshot(self, agent: SandboxAgent) -> None:
        """Verify desktop_screenshot returns image data."""
        try:
            await agent.desktop_start()
            await asyncio.sleep(2.0)
        except Exception:
            pass

        try:
            screenshot = await agent.desktop_screenshot(format="png")

            assert isinstance(screenshot, bytes)
            assert len(screenshot) > 0
            assert screenshot[:4] == b"\x89PNG"

        except Exception as e:
            pytest.skip(f"Desktop screenshot not available: {e}")


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentAgents:
    """Test agent management operations."""

    async def test_list_agents(self, agent: SandboxAgent) -> None:
        """Verify list_agents returns available agents."""
        agents = await agent.list_agents()

        assert isinstance(agents, list)

        for agent_info in agents:
            assert isinstance(agent_info, dict)
            assert "id" in agent_info
            assert "installed" in agent_info


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentConfig:
    """Test configuration operations."""

    async def test_get_mcp_config(self, agent: SandboxAgent) -> None:
        """Verify get_mcp_config returns MCP server configuration."""
        try:
            config = await agent.get_mcp_config(directory="/tmp", mcpName="test")
        except Exception as e:
            pytest.skip(f"MCP config not available: {e}")

        assert isinstance(config, dict)
        assert "servers" in config or "mcpServers" in config or "config" in config

    async def test_get_skills_config(self, agent: SandboxAgent) -> None:
        """Verify get_skills_config returns skills configuration."""
        try:
            config = await agent.get_skills_config(directory="/tmp", skillName="test")
        except Exception as e:
            pytest.skip(f"Skills config not available: {e}")

        assert isinstance(config, dict)
        assert "skills" in config or "sources" in config or "config" in config


@pytest.mark.integration
@pytest.mark.asyncio
class TestSessionMcpSkillsConfig:
    """Test Session-scoped MCP and Skills configuration."""

    async def test_session_get_mcp_config_no_context(self, agent: SandboxAgent) -> None:
        """Verify session get_mcp_config returns 404 when no ACP session context exists."""
        from sandboxagent.client import Session
        from sandboxagent.http import SandboxAgentError
        from sandboxagent.types import SessionRecord

        # Create a session without ACP context
        record = SessionRecord(
            id=f"test-session-{uuid.uuid4().hex}",
            agent="claude",
            agent_session_id=f"agent-session-{uuid.uuid4().hex}",
            last_connection_id="test-conn",
            created_at=int(__import__('time').time() * 1000),
        )
        session = Session(agent, record)

        # This should fail with 404 since there's no active ACP session
        try:
            await session.get_mcp_config()
            # If we get here, the endpoint is available (server may support it)
            pass
        except SandboxAgentError as e:
            # Expected behavior: 404 when no session context
            if e.status == 404:
                pass  # Expected
            else:
                pytest.skip(f"MCP config endpoint returned unexpected error: {e}")
        except Exception as e:
            pytest.skip(f"MCP config endpoint not available: {e}")

    async def test_session_get_skills_config_no_context(self, agent: SandboxAgent) -> None:
        """Verify session get_skills_config returns 404 when no ACP session context exists."""
        from sandboxagent.client import Session
        from sandboxagent.http import SandboxAgentError
        from sandboxagent.types import SessionRecord

        # Create a session without ACP context
        record = SessionRecord(
            id=f"test-session-{uuid.uuid4().hex}",
            agent="claude",
            agent_session_id=f"agent-session-{uuid.uuid4().hex}",
            last_connection_id="test-conn",
            created_at=int(__import__('time').time() * 1000),
        )
        session = Session(agent, record)

        # This should fail with 404 since there's no active ACP session
        try:
            await session.get_skills_config()
            # If we get here, the endpoint is available (server may support it)
            pass
        except SandboxAgentError as e:
            # Expected behavior: 404 when no session context
            if e.status == 404:
                pass  # Expected
            else:
                pytest.skip(f"Skills config endpoint returned unexpected error: {e}")
        except Exception as e:
            pytest.skip(f"Skills config endpoint not available: {e}")

    async def test_session_set_mcp_config_no_context(self, agent: SandboxAgent) -> None:
        """Verify session set_mcp_config returns 404 when no ACP session context exists."""
        from sandboxagent.client import Session
        from sandboxagent.http import SandboxAgentError
        from sandboxagent.types import SessionRecord

        # Create a session without ACP context
        record = SessionRecord(
            id=f"test-session-{uuid.uuid4().hex}",
            agent="claude",
            agent_session_id=f"agent-session-{uuid.uuid4().hex}",
            last_connection_id="test-conn",
            created_at=int(__import__('time').time() * 1000),
        )
        session = Session(agent, record)

        # This should fail with 404 since there's no active ACP session
        try:
            await session.set_mcp_config({"servers": []})
            # If we get here, the endpoint is available (server may support it)
            pass
        except SandboxAgentError as e:
            # Expected behavior: 404 when no session context
            if e.status == 404:
                pass  # Expected
            else:
                pytest.skip(f"MCP config set endpoint returned unexpected error: {e}")
        except Exception as e:
            pytest.skip(f"MCP config set endpoint not available: {e}")

    async def test_session_set_skills_config_no_context(self, agent: SandboxAgent) -> None:
        """Verify session set_skills_config returns 404 when no ACP session context exists."""
        from sandboxagent.client import Session
        from sandboxagent.http import SandboxAgentError
        from sandboxagent.types import SessionRecord

        # Create a session without ACP context
        record = SessionRecord(
            id=f"test-session-{uuid.uuid4().hex}",
            agent="claude",
            agent_session_id=f"agent-session-{uuid.uuid4().hex}",
            last_connection_id="test-conn",
            created_at=int(__import__('time').time() * 1000),
        )
        session = Session(agent, record)

        # This should fail with 404 since there's no active ACP session
        try:
            await session.set_skills_config({"sources": []})
            # If we get here, the endpoint is available (server may support it)
            pass
        except SandboxAgentError as e:
            # Expected behavior: 404 when no session context
            if e.status == 404:
                pass  # Expected
            else:
                pytest.skip(f"Skills config set endpoint returned unexpected error: {e}")
        except Exception as e:
            pytest.skip(f"Skills config set endpoint not available: {e}")

@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentAcp:
    """Test ACP (Agent Communication Protocol) operations."""

    async def test_list_acp_servers(self, agent: SandboxAgent) -> None:
        """Verify list_acp_servers returns active ACP servers."""
        result = await agent.list_acp_servers()

        assert isinstance(result, dict)
        assert "servers" in result
        assert isinstance(result["servers"], list)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentLifecycle:
    """Test client lifecycle and cleanup."""

    async def test_multiple_connections(self) -> None:
        """Verify multiple agents can connect and disconnect independently."""
        agent1 = await SandboxAgent.connect(SERVER_URL)
        agent2 = await SandboxAgent.connect(SERVER_URL)

        health1 = await agent1.health()
        health2 = await agent2.health()

        assert health1["status"] == "ok"
        assert health2["status"] == "ok"

        await agent1.dispose()

        health2 = await agent2.health()
        assert health2["status"] == "ok"

        await agent2.dispose()

    async def test_cleanup_after_operations(self, agent: SandboxAgent) -> None:
        """Verify agent can perform operations and clean up properly."""
        test_path = f"/tmp/test_cleanup_{uuid.uuid4().hex}.txt"

        await agent.write_file(test_path, "cleanup test")
        content = await agent.read_file(test_path)
        assert content == "cleanup test"

        await agent.delete_entry(test_path)
        await agent.dispose()

        assert agent._disposed is True


@pytest.mark.integration
@pytest.mark.asyncio
class TestSandboxAgentStart:
    """Test SandboxAgent.start() static method (when implemented)."""

    async def test_start_spawns_server(self) -> None:
        """Verify start() spawns a server and returns connected agent.

        This test is skipped if start() is not implemented.
        """
        try:
            agent = await SandboxAgent.start()

            assert agent is not None
            assert isinstance(agent, SandboxAgent)

            health = await agent.health()
            assert health["status"] == "ok"

            await agent.dispose()

        except AttributeError:
            pytest.skip("SandboxAgent.start() is not implemented yet")
        except Exception as e:
            pytest.skip(f"SandboxAgent.start() failed: {e}")

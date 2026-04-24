"""Tests for newly added HTTP API methods."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from httpx import Response

from sandboxagent import SandboxAgent, Session
from sandboxagent.types import SessionRecord

BASE_URL = "http://localhost:2468"


@pytest.fixture
def agent() -> SandboxAgent:
    return SandboxAgent(BASE_URL)


class TestMkdirFs:
    """Test mkdir_fs method."""

    @pytest.mark.asyncio
    async def test_mkdir_fs(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """mkdir_fs creates a directory."""
        respx_mock.post(f"{BASE_URL}/v1/fs/mkdir").mock(
            return_value=Response(200, json={"success": True})
        )
        result = await agent.mkdir_fs("/test/dir")
        assert result["success"] is True


class TestUploadFsBatch:
    """Test upload_fs_batch method."""

    @pytest.mark.asyncio
    async def test_upload_fs_batch(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """upload_fs_batch uploads files."""
        respx_mock.post(f"{BASE_URL}/v1/fs/batch").mock(
            return_value=Response(200, json={"uploaded": 2})
        )
        files = [{"path": "/a.txt", "content": "hello"}, {"path": "/b.txt", "content": "world"}]
        result = await agent.upload_fs_batch(files)
        assert result["uploaded"] == 2


class TestKillProcess:
    """Test kill_process method."""

    @pytest.mark.asyncio
    async def test_kill_process(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """kill_process sends a signal."""
        respx_mock.post(f"{BASE_URL}/v1/processes/proc-123/kill").mock(
            return_value=Response(200, json={"success": True})
        )
        result = await agent.kill_process("proc-123", signal="SIGTERM")
        assert result["success"] is True


class TestDeleteProcess:
    """Test delete_process method."""

    @pytest.mark.asyncio
    async def test_delete_process(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """delete_process removes a process."""
        respx_mock.delete(f"{BASE_URL}/v1/processes/proc-123").mock(
            return_value=Response(204)
        )
        await agent.delete_process("proc-123")


class TestResizeProcessTerminal:
    """Test resize_process_terminal method."""

    @pytest.mark.asyncio
    async def test_resize_process_terminal(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """resize_process_terminal resizes the terminal."""
        respx_mock.post(f"{BASE_URL}/v1/processes/proc-123/terminal/resize").mock(
            return_value=Response(200, json={"success": True})
        )
        result = await agent.resize_process_terminal("proc-123", cols=120, rows=40)
        assert result["success"] is True


class TestMcpConfig:
    """Test MCP config methods."""

    @pytest.mark.asyncio
    async def test_set_mcp_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """set_mcp_config updates MCP config on session."""
        respx_mock.put(f"{BASE_URL}/v1/sessions/sess-123/mcp/config").mock(
            return_value=Response(200, json={"success": True})
        )
        record = SessionRecord(
            id="sess-123",
            agent="test-agent",
            agent_session_id="agent-sess-123",
            last_connection_id="conn-123",
            created_at=1234567890,
        )
        session = Session(sandbox=agent, record=record)
        await session.set_mcp_config({"server": "http://localhost:3000"})
        await session.set_mcp_config({"server": "http://localhost:3000"})

    @pytest.mark.asyncio
    async def test_delete_mcp_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """delete_mcp_config removes global MCP config."""
        respx_mock.delete(f"{BASE_URL}/v1/mcp").mock(
            return_value=Response(204)
        )
        await agent.delete_mcp_config()


class TestSkillsConfig:
    """Test skills config methods."""

    @pytest.mark.asyncio
    async def test_set_skills_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """set_skills_config updates skills config on session."""
        respx_mock.put(f"{BASE_URL}/v1/sessions/sess-123/skills/config").mock(
            return_value=Response(200, json={"success": True})
        )
        record = SessionRecord(
            id="sess-123",
            agent="test-agent",
            agent_session_id="agent-sess-123",
            last_connection_id="conn-123",
            created_at=1234567890,
        )
        session = Session(sandbox=agent, record=record)
        await session.set_skills_config({"enabled": ["git", "file"]})
        await session.set_skills_config({"enabled": ["git", "file"]})

    @pytest.mark.asyncio
    async def test_delete_skills_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """delete_skills_config removes global skills config."""
        respx_mock.delete(f"{BASE_URL}/v1/skills").mock(
            return_value=Response(204)
        )
        await agent.delete_skills_config()


class TestProcessConfig:
    """Test process config methods."""

    @pytest.mark.asyncio
    async def test_get_process_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """get_process_config returns config."""
        respx_mock.get(f"{BASE_URL}/v1/processes/config").mock(
            return_value=Response(200, json={"shell": "/bin/bash"})
        )
        result = await agent.get_process_config()
        assert result["shell"] == "/bin/bash"

    @pytest.mark.asyncio
    async def test_set_process_config(self, agent: SandboxAgent, respx_mock: respx.MockRouter) -> None:
        """set_process_config updates config."""
        respx_mock.post(f"{BASE_URL}/v1/processes/config").mock(
            return_value=Response(200, json={"success": True})
        )
        result = await agent.set_process_config({"shell": "/bin/zsh"})
        assert result["success"] is True

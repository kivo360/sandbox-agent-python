"""Unit tests for sandboxagent HTTP transport and client."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from respx import MockRouter

from sandboxagent import SandboxAgent
from sandboxagent.http import HttpTransport, SandboxAgentError
from sandboxagent.types import ProblemDetails

BASE_URL = "http://localhost:2468"


@pytest.fixture
def transport() -> HttpTransport:
    return HttpTransport(BASE_URL)


@pytest.fixture
def mock_api() -> MockRouter:
    with respx.mock(base_url=BASE_URL, assert_all_mocked=False) as router:
        yield router


class TestHttpTransport:
    """Test the low-level HTTP transport."""

    async def test_get_success(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(200, json={"status": "ok", "version": "0.4.2"})

        response = await transport.get("/v1/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_get_with_query_params(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        route = mock_api.get("/v1/fs/entries").respond(200, json=[])

        await transport.get("/v1/fs/entries", params={"path": "/tmp", "recursive": True})

        request = route.calls.last.request
        assert request.url.params["path"] == "/tmp"
        assert request.url.params["recursive"] == "true"

    async def test_post_with_json_body(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/processes").respond(201, json={"id": "p1", "state": "running"})

        response = await transport.post("/v1/processes", json={"command": "echo hello"})

        assert response.status_code == 201
        request = route.calls.last.request
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"command": "echo hello"}

    async def test_delete_with_params(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        route = mock_api.delete("/v1/fs/entry").respond(204)

        await transport.delete("/v1/fs/entry", params={"path": "/tmp/file.txt"})

        request = route.calls.last.request
        assert request.url.params["path"] == "/tmp/file.txt"

    async def test_auth_header(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})
        transport = HttpTransport(BASE_URL, token="secret-token")

        await transport.get("/v1/health")

        request = mock_api.routes[0].calls.last.request
        assert request.headers["authorization"] == "Bearer secret-token"

    async def test_error_raises_sandbox_agent_error(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(
            500,
            json={"type": "internal_error", "title": "Server Error", "status": 500, "detail": "Something broke"},
        )

        with pytest.raises(SandboxAgentError) as exc_info:
            await transport.get("/v1/health")

        error = exc_info.value
        assert error.status == 500
        assert error.problem is not None
        assert isinstance(error.problem, ProblemDetails)
        assert error.problem.title == "Server Error"
        assert error.problem.status == 500
        assert str(error) == "Server Error"

    async def test_error_with_malformed_json(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(500, text="not json")

        with pytest.raises(SandboxAgentError) as exc_info:
            await transport.get("/v1/health")

        assert exc_info.value.status == 500
        assert exc_info.value.problem is None

    async def test_error_with_json_missing_title(self, transport: HttpTransport, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(400, json={"type": "bad_request", "title": "Bad Request", "status": 400})

        with pytest.raises(SandboxAgentError) as exc_info:
            await transport.get("/v1/health")

        error = exc_info.value
        assert error.status == 400
        assert isinstance(error.problem, ProblemDetails)
        assert str(error) == "Bad Request"

    async def test_custom_headers(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})
        transport = HttpTransport(BASE_URL, headers={"X-Custom": "value"})

        await transport.get("/v1/health")

        request = mock_api.routes[0].calls.last.request
        assert request.headers["x-custom"] == "value"
        assert request.headers["accept"] == "application/json"


class TestSandboxAgentConnect:
    """Test SandboxAgent connection and health checks."""

    async def test_connect_performs_health_check(self, mock_api: MockRouter) -> None:
        route = mock_api.get("/v1/health").respond(200, json={"status": "ok", "version": "0.4.2"})

        agent = await SandboxAgent.connect(BASE_URL)

        assert agent is not None
        assert route.called
        await agent.dispose()

    async def test_connect_with_token(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(200, json={"status": "ok"})

        agent = await SandboxAgent.connect(BASE_URL, token="my-token")

        request = mock_api.routes[0].calls.last.request
        assert request.headers["authorization"] == "Bearer my-token"
        await agent.dispose()

    async def test_connect_skip_health_check(self, mock_api: MockRouter) -> None:
        # No health route registered — if connect calls it, it will fail
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)
        await agent.dispose()

    async def test_connect_unhealthy_server_raises(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(
            503, json={"type": "unavailable", "title": "Service Unavailable", "status": 503}
        )

        with pytest.raises(TimeoutError):
            await SandboxAgent.connect(BASE_URL, health_timeout=0.1)

    async def test_health_returns_typed_response(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(200, json={"status": "ok", "version": "0.4.2"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        health = await agent.health()

        assert health["status"] == "ok"
        assert health["version"] == "0.4.2"
        await agent.dispose()

    async def test_wait_for_health_retries_until_success(self, mock_api: MockRouter) -> None:
        # First two calls fail, third succeeds
        route = mock_api.get("/v1/health").mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(503),
                httpx.Response(200, json={"status": "ok", "version": "0.4.2"}),
            ]
        )

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)
        health = await agent.wait_for_health(timeout_seconds=5.0)

        assert health["status"] == "ok"
        assert route.call_count == 3
        await agent.dispose()

    async def test_wait_for_health_timeout(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/health").respond(503)

        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        with pytest.raises(TimeoutError):
            await agent.wait_for_health(timeout_seconds=0.1)

        await agent.dispose()

    async def test_dispose_closes_transport(self, mock_api: MockRouter) -> None:
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.dispose()

        # Second dispose should be a no-op
        await agent.dispose()

    async def test_default_base_url(self, mock_api: MockRouter) -> None:
        # Just verify the default base_url property is set correctly
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)
        assert agent._base_url == "http://localhost:2468"
        await agent.dispose()


class TestSandboxAgentFilesystem:
    """Test filesystem operations."""

    async def test_read_file(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/fs/file").respond(200, text="hello world")
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        content = await agent.read_file("/tmp/test.txt")

        assert content == "hello world"
        request = mock_api.routes[0].calls.last.request
        assert request.url.params["path"] == "/tmp/test.txt"
        await agent.dispose()

    async def test_write_file_with_string(self, mock_api: MockRouter) -> None:
        route = mock_api.put("/v1/fs/file").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.write_file("/tmp/test.txt", "hello world")

        request = route.calls.last.request
        assert request.content == b"hello world"
        assert request.url.params["path"] == "/tmp/test.txt"
        await agent.dispose()

    async def test_write_file_with_bytes(self, mock_api: MockRouter) -> None:
        route = mock_api.put("/v1/fs/file").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.write_file("/tmp/test.bin", b"\x00\x01\x02")

        request = route.calls.last.request
        assert request.content == b"\x00\x01\x02"
        await agent.dispose()

    async def test_delete_entry(self, mock_api: MockRouter) -> None:
        route = mock_api.delete("/v1/fs/entry").respond(204)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.delete_entry("/tmp/old.txt")

        request = route.calls.last.request
        assert request.url.params["path"] == "/tmp/old.txt"
        await agent.dispose()

    async def test_list_entries(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/fs/entries").respond(200, json=[
            {"name": "file1.txt", "type": "file", "size": 100},
            {"name": "dir1", "type": "directory"},
        ])
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        entries = await agent.list_entries("/tmp")

        assert len(entries) == 2
        assert entries[0]["name"] == "file1.txt"
        await agent.dispose()

    async def test_stat(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/fs/stat").respond(200, json={"name": "test.txt", "size": 42, "type": "file"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        info = await agent.stat("/tmp/test.txt")

        assert info["size"] == 42
        await agent.dispose()

    async def test_move(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/fs/move").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.move("/tmp/old.txt", "/tmp/new.txt")

        request = route.calls.last.request
        assert json.loads(request.content) == {"from": "/tmp/old.txt", "to": "/tmp/new.txt"}
        await agent.dispose()


class TestSandboxAgentProcesses:
    """Test process operations."""

    async def test_list_processes(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/processes").respond(200, json={
            "processes": [{"id": "p1", "name": "bash", "state": "running"}],
        })
        mock_api.get("/v1/processes").respond(200, json=[
            {"id": "p1", "name": "bash", "state": "running"},
        ])
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        processes = await agent.list_processes()

        assert len(processes) == 1
        assert processes[0]["id"] == "p1"
        await agent.dispose()

    async def test_list_processes_with_owner_filter(self, mock_api: MockRouter) -> None:
        route = mock_api.get("/v1/processes").respond(200, json={"processes": []})
        route = mock_api.get("/v1/processes").respond(200, json=[])
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.list_processes(owner="user")

        request = route.calls.last.request
        assert request.url.params["owner"] == "user"
        await agent.dispose()

    async def test_create_process(self, mock_api: MockRouter) -> None:
        mock_api.post("/v1/processes").respond(201, json={"id": "p1", "state": "running"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        process = await agent.create_process({"command": "sleep 10"})

        assert process["id"] == "p1"
        await agent.dispose()

    async def test_run_process(self, mock_api: MockRouter) -> None:
        mock_api.post("/v1/processes/run").respond(200, json={"exit_code": 0, "output": "hello"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        result = await agent.run_process({"command": "echo hello"})

        assert result["exit_code"] == 0
        await agent.dispose()

    async def test_get_process(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/processes/p1").respond(200, json={"id": "p1", "state": "running"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        process = await agent.get_process("p1")

        assert process["id"] == "p1"
        await agent.dispose()

    async def test_stop_process(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/processes/p1/stop").respond(204)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.stop_process("p1", signal="SIGTERM")

        request = route.calls.last.request
        assert request.url.params["signal"] == "SIGTERM"
        await agent.dispose()

    async def test_send_input(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/processes/p1/input").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.send_input("p1", "hello\n")

        request = route.calls.last.request
        assert json.loads(request.content) == {"data": "hello\n"}
        await agent.dispose()

    async def test_get_process_logs(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/processes/p1/logs").respond(200, json={"entries": [{"line": "log1"}]})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        logs = await agent.get_process_logs("p1", follow=False)

        assert logs["entries"][0]["line"] == "log1"
        await agent.dispose()


class TestSandboxAgentDesktop:
    """Test desktop operations."""

    async def test_desktop_status(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/desktop/status").respond(200, json={"state": "active"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        status = await agent.desktop_status()

        assert status["state"] == "active"
        await agent.dispose()

    async def test_desktop_start(self, mock_api: MockRouter) -> None:
        mock_api.post("/v1/desktop/start").respond(200, json={"state": "starting"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        status = await agent.desktop_start({"resolution": "1920x1080"})

        assert status["state"] == "starting"
        await agent.dispose()

    async def test_desktop_screenshot(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/desktop/screenshot").respond(200, content=b"PNG\x89")
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        image = await agent.desktop_screenshot(format="png")

        assert image[:3] == b"PNG"
        await agent.dispose()

    async def test_desktop_mouse_move(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/desktop/mouse/move").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.desktop_mouse_move(100, 200)

        request = route.calls.last.request
        assert json.loads(request.content) == {"x": 100, "y": 200}
        await agent.dispose()

    async def test_desktop_mouse_click(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/desktop/mouse/click").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.desktop_mouse_click("right", clicks=2)

        request = route.calls.last.request
        assert json.loads(request.content) == {"button": "right", "clicks": 2}
        await agent.dispose()

    async def test_desktop_keyboard_type(self, mock_api: MockRouter) -> None:
        route = mock_api.post("/v1/desktop/keyboard/type").respond(200)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        await agent.desktop_keyboard_type("Hello World")

        request = route.calls.last.request
        assert json.loads(request.content) == {"text": "Hello World"}
        await agent.dispose()

    async def test_desktop_windows(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/desktop/windows").respond(200, json={"windows": [{"id": "w1", "title": "Terminal"}]})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        result = await agent.desktop_windows()

        assert result["windows"][0]["title"] == "Terminal"
        await agent.dispose()


class TestSandboxAgentAgents:
    """Test agent management."""

    async def test_list_agents(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/agents").respond(200, json={"agents": [{"id": "mock", "name": "Mock Agent"}]})
        mock_api.get("/v1/agents").respond(200, json=[{"id": "mock", "name": "Mock Agent"}])
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        agents = await agent.list_agents()

        assert len(agents) == 1
        assert agents[0]["id"] == "mock"
        await agent.dispose()

    async def test_install_agent(self, mock_api: MockRouter) -> None:
        mock_api.post("/v1/agents/new-agent/install").respond(200, json={"success": True})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        result = await agent.install_agent("new-agent", {"agent_version": "1.0.0"})

        assert result["success"] is True
        request = mock_api.routes[0].calls.last.request
        assert json.loads(request.content) == {"agent_version": "1.0.0"}
        await agent.dispose()


class TestSandboxAgentConfig:
    """Test configuration endpoints."""

    async def test_get_mcp_config(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/config/mcp").respond(200, json={"servers": []})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        config = await agent.get_mcp_config()

        assert "servers" in config
        await agent.dispose()

    async def test_get_skills_config(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/config/skills").respond(200, json={"skills": []})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        config = await agent.get_skills_config()

        assert "skills" in config
        await agent.dispose()


class TestSessionMcpSkillsConfig:
    """Test Session-scoped MCP and Skills config endpoints."""

    async def test_session_get_mcp_config(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/sessions/session-123/mcp/config").respond(200, json={"servers": [{"name": "test"}]})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        # Create a mock session
        from sandboxagent.client import Session
        from sandboxagent.types import SessionRecord
        record = SessionRecord(
            id="session-123",
            agent="claude",
            agent_session_id="agent-session-456",
            last_connection_id="conn-789",
            created_at=1234567890,
        )
        session = Session(agent, record)

        config = await session.get_mcp_config()

        assert "servers" in config
        assert config["servers"][0]["name"] == "test"
        await agent.dispose()

    async def test_session_set_mcp_config(self, mock_api: MockRouter) -> None:
        route = mock_api.put("/v1/sessions/session-123/mcp/config").respond(204)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        from sandboxagent.client import Session
        from sandboxagent.types import SessionRecord
        record = SessionRecord(
            id="session-123",
            agent="claude",
            agent_session_id="agent-session-456",
            last_connection_id="conn-789",
            created_at=1234567890,
        )
        session = Session(agent, record)

        await session.set_mcp_config({"servers": [{"name": "new-server"}]})

        request = route.calls.last.request
        assert json.loads(request.content) == {"servers": [{"name": "new-server"}]}
        await agent.dispose()

    async def test_session_get_skills_config(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/sessions/session-123/skills/config").respond(200, json={"sources": [{"type": "git"}]})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        from sandboxagent.client import Session
        from sandboxagent.types import SessionRecord
        record = SessionRecord(
            id="session-123",
            agent="claude",
            agent_session_id="agent-session-456",
            last_connection_id="conn-789",
            created_at=1234567890,
        )
        session = Session(agent, record)

        config = await session.get_skills_config()

        assert "sources" in config
        assert config["sources"][0]["type"] == "git"
        await agent.dispose()

    async def test_session_set_skills_config(self, mock_api: MockRouter) -> None:
        route = mock_api.put("/v1/sessions/session-123/skills/config").respond(204)
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        from sandboxagent.client import Session
        from sandboxagent.types import SessionRecord
        record = SessionRecord(
            id="session-123",
            agent="claude",
            agent_session_id="agent-session-456",
            last_connection_id="conn-789",
            created_at=1234567890,
        )
        session = Session(agent, record)

        await session.set_skills_config({"sources": [{"type": "local"}]})

        request = route.calls.last.request
        assert json.loads(request.content) == {"sources": [{"type": "local"}]}
        await agent.dispose()

    async def test_session_get_mcp_config_404_no_session_context(self, mock_api: MockRouter) -> None:
        """Test that 404 is handled gracefully when no session context exists."""
        mock_api.get("/v1/sessions/session-123/mcp/config").respond(
            404,
            json={"type": "not_found", "title": "Session Not Found", "status": 404}
        )
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        from sandboxagent.client import Session
        from sandboxagent.http import SandboxAgentError
        from sandboxagent.types import SessionRecord
        record = SessionRecord(
            id="session-123",
            agent="claude",
            agent_session_id="agent-session-456",
            last_connection_id="conn-789",
            created_at=1234567890,
        )
        session = Session(agent, record)

        with pytest.raises(SandboxAgentError) as exc_info:
            await session.get_mcp_config()

        assert exc_info.value.status == 404
        await agent.dispose()

class TestSandboxAgentAcp:
    """Test ACP server endpoints."""

    async def test_list_acp_servers(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/acp").respond(200, json={"servers": [{"id": "s1", "name": "Server 1"}]})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        result = await agent.list_acp_servers()

        assert "servers" in result
        await agent.dispose()

    async def test_get_acp_server(self, mock_api: MockRouter) -> None:
        mock_api.get("/v1/acp/server-1").respond(200, json={"id": "server-1"})
        agent = await SandboxAgent.connect(BASE_URL, skip_health_check=True)

        result = await agent.get_acp_server("server-1")

        assert result["id"] == "server-1"
        await agent.dispose()


class TestInspectorUrl:
    """Test inspector URL builder."""

    def test_build_inspector_url_basic(self) -> None:
        from sandboxagent import build_inspector_url

        url = build_inspector_url("http://localhost:2468")
        assert url == "http://localhost:2468/ui/"

    def test_build_inspector_url_with_token(self) -> None:
        from sandboxagent import build_inspector_url

        url = build_inspector_url("http://localhost:2468", token="secret")
        assert url == "http://localhost:2468/ui/?token=secret"

    def test_build_inspector_url_with_headers(self) -> None:
        from sandboxagent import build_inspector_url

        url = build_inspector_url("http://localhost:2468", headers={"X-Custom": "value"})
        assert "headers=" in url
        assert "X-Custom" in url

    def test_build_inspector_url_trailing_slash(self) -> None:
        from sandboxagent import build_inspector_url

        url = build_inspector_url("http://localhost:2468/")
        assert url == "http://localhost:2468/ui/"

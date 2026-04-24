"""Simple integration tests for workspace file and environment variable injection."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from respx import MockRouter

from sandboxagent import SandboxAgent
from sandboxagent.providers.types import SandboxProvider

BASE_URL = "http://test-sandbox.local"


class MockProvider(SandboxProvider):
    """Mock sandbox provider for testing workspace injection."""

    def __init__(
        self,
        sandbox_id: str = "test-sandbox-123",
        base_url: str = BASE_URL,
        default_cwd: str | None = "/workspace",
    ) -> None:
        self._sandbox_id = sandbox_id
        self._base_url = base_url
        self._default_cwd = default_cwd
        self.env: dict[str, str] = {}  # type: ignore[assignment]
        self.set_env_calls: list[dict[str, str]] = []

    @property
    def name(self) -> str:
        return "mock"

    async def create(self) -> str:
        return self._sandbox_id

    async def destroy(self, sandbox_id: str) -> None:
        pass

    async def get_url(self, sandbox_id: str) -> str:
        return self._base_url

    def set_env(self, env: dict[str, str]) -> None:
        self.set_env_calls.append(env)
        current = self.env or {}
        self.env = {**current, **env}

    @property
    def default_cwd(self) -> str | None:
        return self._default_cwd


@pytest.fixture
def respx_mock() -> Any:
    with respx.mock(base_url=BASE_URL, assert_all_mocked=False, assert_all_called=False) as router:
        yield router


@pytest.mark.asyncio
async def test_start_with_workspace_files(respx_mock: MockRouter) -> None:
    """Test that workspace files trigger _bootstrap_workspace."""
    provider = MockProvider()
    respx_mock.get("/v1/health").respond(200, json={"status": "ok"})
    respx_mock.post("/v1/fs/mkdir").respond(200, json={"success": True})
    respx_mock.put("/v1/fs/file?path=/workspace/test.txt").respond(200, text="ok")

    agent = await SandboxAgent.start(
        provider=provider,
        workspace_files={"test.txt": "hello"},
        skip_health_check=True,
    )

    # Verify file was written via API
    await agent.dispose()


@pytest.mark.asyncio
async def test_provider_set_env_called(respx_mock: MockRouter) -> None:
    """Test that provider.set_env is called with workspace_env."""
    provider = MockProvider()
    respx_mock.get("/v1/health").respond(200, json={"status": "ok"})
    respx_mock.post("/v1/fs/mkdir").respond(200, json={"success": True})
    respx_mock.put("/v1/fs/file?path=/workspace/.env").respond(200, text="ok")

    workspace_env = {"API_KEY": "test123"}

    agent = await SandboxAgent.start(
        provider=provider,
        workspace_env=workspace_env,
        skip_health_check=True,
    )

    assert len(provider.set_env_calls) == 1
    assert provider.set_env_calls[0] == workspace_env
    assert provider.env is not None
    assert provider.env.get("API_KEY") == "test123"

    await agent.dispose()


@pytest.mark.asyncio
async def test_both_workspace_files_and_env(respx_mock: MockRouter) -> None:
    """Test that both workspace_files and workspace_env work together."""
    provider = MockProvider()
    respx_mock.get("/v1/health").respond(200, json={"status": "ok"})
    respx_mock.post("/v1/fs/mkdir").respond(200, json={"success": True})
    respx_mock.put("/v1/fs/file?path=/workspace/app.py").respond(200, text="ok")
    respx_mock.put("/v1/fs/file?path=/workspace/.env").respond(200, text="ok")

    agent = await SandboxAgent.start(
        provider=provider,
        workspace_files={"app.py": "print('hello')"},
        workspace_env={"PORT": "8080"},
        skip_health_check=True,
    )

    # Verify set_env was called
    assert len(provider.set_env_calls) == 1
    assert provider.set_env_calls[0] == {"PORT": "8080"}

    await agent.dispose()

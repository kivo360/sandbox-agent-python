"""Tests for SandboxAgent.clone_repo() method."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from sandboxagent import GitCloneError, SandboxAgent


@pytest.fixture
def sandbox_agent():
    """Create a SandboxAgent instance with mocked transport."""
    agent = SandboxAgent(base_url="http://localhost:8080", token="test-token")
    agent._transport = AsyncMock()
    return agent


class TestClonePublicRepo:
    """Tests for cloning public repositories."""

    @pytest.mark.asyncio
    async def test_clone_public_repo_success(self, sandbox_agent: SandboxAgent) -> None:
        """Cloning a public repo without a token succeeds."""
        sandbox_agent._transport.post.return_value = Response(
            200,
            json={"exit_code": 0, "stdout": "Cloning into 'repo'...\n", "stderr": ""},
        )

        result = await sandbox_agent.clone_repo("https://github.com/example/repo.git")

        assert result["exit_code"] == 0
        assert "Cloning into" in result["stdout"]

    @pytest.mark.asyncio
    async def test_clone_no_token_no_askpass_script(self, sandbox_agent: SandboxAgent) -> None:
        """No token means no askpass script should be written."""
        sandbox_agent._transport.post.return_value = Response(
            200, json={"exit_code": 0, "stdout": "", "stderr": ""}
        )

        # Mock write_file and delete_entry to track calls
        with patch.object(sandbox_agent, "write_file", AsyncMock()) as mock_write:
            with patch.object(sandbox_agent, "delete_entry", AsyncMock()) as mock_delete:
                await sandbox_agent.clone_repo("https://github.com/example/repo.git")

                # No token helper script should be written.
                mock_write.assert_not_awaited()
                mock_delete.assert_not_awaited()


class TestClonePrivateRepo:
    """Tests for cloning private repositories with authentication."""

    @pytest.mark.asyncio
    async def test_clone_private_repo_with_token(self, sandbox_agent: SandboxAgent) -> None:
        """A token triggers the GIT_ASKPASS pattern and keeps the URL clean."""
        token = "ghp_secrettoken123"

        # Track what gets written
        written_files: list[tuple[str, str]] = []

        async def mock_write_file(path: str, content: str | bytes) -> None:
            written_files.append((path, content if isinstance(content, str) else content.decode()))

        with patch.object(sandbox_agent, "write_file", mock_write_file):
            with patch.object(sandbox_agent, "delete_entry", AsyncMock()) as mock_delete:
                # First call is chmod, second is git clone
                sandbox_agent._transport.post.side_effect = [
                    Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""}),  # chmod
                    Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""}),  # git clone
                ]

                await sandbox_agent.clone_repo(
                    "https://github.com/example/private.git",
                    token=token,
                )

        # An askpass helper script must have been written.
        assert len(written_files) == 1
        written_path, written_content = written_files[0]
        assert written_path.startswith("/tmp/.git-askpass-")
        # Script reads token from env var, not hardcoded.
        assert "$GIT_TOKEN" in written_content
        assert token not in written_content


class TestCloneOptions:
    """Tests for optional flags like branch, depth, and custom paths."""

    @pytest.mark.asyncio
    async def test_clone_with_branch_and_depth(self, sandbox_agent: SandboxAgent) -> None:
        """Both --branch and --depth flags are forwarded to git."""
        sandbox_agent._transport.post.return_value = Response(
            200, json={"exit_code": 0, "stdout": "", "stderr": ""}
        )

        await sandbox_agent.clone_repo(
            "https://github.com/example/repo.git",
            branch="main",
            depth=1,
        )

        # Get the git clone call (not chmod)
        calls = sandbox_agent._transport.post.call_args_list
        assert len(calls) == 1
        config = calls[0][1]["json"]
        args = config["args"]
        assert "--branch" in args
        assert args[args.index("--branch") + 1] == "main"
        assert "--single-branch" in args
        assert "--depth" in args
        assert args[args.index("--depth") + 1] == "1"

    @pytest.mark.asyncio
    async def test_clone_custom_path(self, sandbox_agent: SandboxAgent) -> None:
        """A custom destination path is appended to the git arguments."""
        sandbox_agent._transport.post.return_value = Response(
            200, json={"exit_code": 0, "stdout": "", "stderr": ""}
        )

        await sandbox_agent.clone_repo(
            "https://github.com/example/repo.git",
            path="/workspace/my-repo",
        )

        config = sandbox_agent._transport.post.call_args[1]["json"]
        assert config["args"][-1] == "/workspace/my-repo"


class TestCloneErrors:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_clone_authentication_failure(self, sandbox_agent: SandboxAgent) -> None:
        """Exit code 128 with auth error raises GitCloneError with category 'auth'."""
        token = "ghp_supersecrettoken"

        with patch.object(sandbox_agent, "write_file", AsyncMock()):
            with patch.object(sandbox_agent, "delete_entry", AsyncMock()):
                # chmod succeeds, git clone fails with token in error (to test sanitization)
                sandbox_agent._transport.post.side_effect = [
                    Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""}),  # chmod
                    Response(
                        200,
                        json={
                            "exit_code": 128,
                            "stdout": "",
                            "stderr": f"fatal: Authentication failed for https://{token}@github.com/example/repo.git\n",
                        },
                    ),  # git clone
                ]

                with pytest.raises(GitCloneError) as exc_info:
                    await sandbox_agent.clone_repo(
                        "https://github.com/example/repo.git",
                        token=token,
                    )

                assert exc_info.value.category == "auth"
                assert token not in str(exc_info.value)
                assert "[REDACTED]" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_repo_not_found(self, sandbox_agent: SandboxAgent) -> None:
        """A missing repository raises GitCloneError with category 'not_found'."""
        sandbox_agent._transport.post.return_value = Response(
            200,
            json={
                "exit_code": 128,
                "stdout": "",
                "stderr": "fatal: remote: 404 Repository not found\n",
            },
        )

        with pytest.raises(GitCloneError) as exc_info:
            await sandbox_agent.clone_repo("https://github.com/example/unknown.git")

        assert exc_info.value.category == "not_found"

    @pytest.mark.asyncio
    async def test_clone_network_error(self, sandbox_agent: SandboxAgent) -> None:
        """A DNS failure raises GitCloneError with category 'network'."""
        sandbox_agent._transport.post.return_value = Response(
            200,
            json={
                "exit_code": 128,
                "stdout": "",
                "stderr": (
                    "fatal: unable to access 'https://github.com/example/repo.git/': "
                    "Could not resolve host: github.com\n"
                ),
            },
        )

        with pytest.raises(GitCloneError) as exc_info:
            await sandbox_agent.clone_repo("https://github.com/example/repo.git")

        assert exc_info.value.category == "network"
        assert "Could not resolve host" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_cleans_up_askpass_script(self, sandbox_agent: SandboxAgent) -> None:
        """The askpass helper script is deleted even when cloning fails."""
        token = "ghp_secrettoken"
        written_path: str | None = None

        async def mock_write_file(path: str, content: str | bytes) -> None:
            nonlocal written_path
            written_path = path

        with patch.object(sandbox_agent, "write_file", mock_write_file):
            with patch.object(sandbox_agent, "delete_entry", AsyncMock()) as mock_delete:
                # chmod succeeds, git clone fails
                sandbox_agent._transport.post.side_effect = [
                    Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""}),  # chmod
                    Response(
                        200,
                        json={"exit_code": 128, "stdout": "", "stderr": "fatal: Authentication failed\n"},
                    ),  # git clone
                ]

                with pytest.raises(GitCloneError):
                    await sandbox_agent.clone_repo(
                        "https://github.com/example/private.git",
                        token=token,
                    )

                # delete_entry must be called to remove the script.
                mock_delete.assert_awaited_once_with(written_path)

    @pytest.mark.asyncio
    async def test_clone_url_with_embedded_credentials_rejected(self, sandbox_agent: SandboxAgent) -> None:
        """URLs that already contain username/password are rejected immediately."""
        with pytest.raises(GitCloneError, match="embedded credentials"):
            await sandbox_agent.clone_repo("https://user:pass@github.com/example/repo.git")

        # run_process should never have been reached.
        sandbox_agent._transport.post.assert_not_awaited()


class TestCloneTimeoutAndEnv:
    """Tests for timeout propagation and environment variables."""

    @pytest.mark.asyncio
    async def test_clone_timeout_propagation(self, sandbox_agent) -> None:
        """The timeout parameter is forwarded to run_process."""
        custom_timeout = 600
        sandbox_agent._transport.post.return_value = Response(
            200, json={"exit_code": 0, "stdout": "", "stderr": ""}
        )

        await sandbox_agent.clone_repo(
            "https://github.com/example/repo.git",
            timeout=custom_timeout,
        )

        config = sandbox_agent._transport.post.call_args[1]["json"]
        assert config["timeout"] == custom_timeout

    @pytest.mark.asyncio
    async def test_clone_sets_git_terminal_prompt(self, sandbox_agent: SandboxAgent) -> None:
        """GIT_TERMINAL_PROMPT=0 is set to prevent interactive prompts."""
        sandbox_agent._transport.post.return_value = Response(
            200, json={"exit_code": 0, "stdout": "", "stderr": ""}
        )

        await sandbox_agent.clone_repo("https://github.com/example/repo.git")

        config = sandbox_agent._transport.post.call_args[1]["json"]
        assert config["env"]["GIT_TERMINAL_PROMPT"] == "0"

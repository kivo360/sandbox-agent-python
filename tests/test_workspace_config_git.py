"""Unit tests for WorkspaceConfig git helper methods."""

import pytest

from sandboxagent.workspace_config import WorkspaceConfig


class TestGitAskpassScript:
    """Tests for WorkspaceConfig.git_askpass_script method."""

    def test_git_askpass_script_content(self) -> None:
        """Script contains case statement for Username/Password and echoes token."""
        token = "ghp_test_token_123"
        result = WorkspaceConfig.git_askpass_script(token)

        assert 'case "$1"' in result or "case \"$1\"" in result
        assert "Username*" in result
        assert "Password*" in result
        assert 'echo "$GIT_TOKEN"' in result or 'echo "$GIT_TOKEN"' in result

    def test_git_askpass_script_valid_shell(self) -> None:
        """Script is syntactically valid shell (basic check)."""
        result = WorkspaceConfig.git_askpass_script("test-token")

        assert result.startswith("#!/bin/sh")
        assert "case" in result
        assert "esac" in result
        assert "#!/bin/sh" in result


class TestGitCloneScript:
    """Tests for WorkspaceConfig.git_clone_script method."""

    def test_git_clone_script_single_repo(self) -> None:
        """Script contains git clone command for one repository."""
        repos = [{"url": "https://github.com/user/repo.git"}]
        result = WorkspaceConfig.git_clone_script(repos)

        assert "git clone https://github.com/user/repo.git" in result

    def test_git_clone_script_multiple_repos(self) -> None:
        """Script contains multiple git clone commands."""
        repos = [
            {"url": "https://github.com/user/repo1.git"},
            {"url": "https://github.com/user/repo2.git"},
        ]
        result = WorkspaceConfig.git_clone_script(repos)

        assert "git clone https://github.com/user/repo1.git" in result
        assert "git clone https://github.com/user/repo2.git" in result

    def test_git_clone_script_with_branch_depth(self) -> None:
        """Script contains --branch and --depth flags when specified."""
        repos = [
            {
                "url": "https://github.com/user/repo.git",
                "branch": "main",
                "depth": 1,
            }
        ]
        result = WorkspaceConfig.git_clone_script(repos)

        assert "--branch main" in result
        assert "--depth 1" in result

    def test_git_clone_script_sets_env(self) -> None:
        """Script exports GIT_TOKEN and GIT_ASKPASS when token is provided."""
        import shlex

        repos = [{"url": "https://github.com/user/repo.git"}]
        result = WorkspaceConfig.git_clone_script(repos, token="secret-token")

        assert f"export GIT_TOKEN={shlex.quote('secret-token')}" in result
        assert 'export GIT_ASKPASS=' in result

    def test_git_clone_script_error_handling(self) -> None:
        """Script contains set -euo pipefail for error handling."""
        repos = [{"url": "https://github.com/user/repo.git"}]
        result = WorkspaceConfig.git_clone_script(repos)

        assert "set -euo pipefail" in result

    def test_git_clone_script_cleanup(self) -> None:
        """Script contains trap for cleanup when token is provided."""
        repos = [{"url": "https://github.com/user/repo.git"}]
        result = WorkspaceConfig.git_clone_script(repos, token="secret-token")

        assert 'trap' in result
        assert "rm -f" in result or "rm -f" in result

    def test_git_clone_script_without_token(self) -> None:
        """No auth-related code when token is None."""
        repos = [{"url": "https://github.com/user/repo.git"}]
        result = WorkspaceConfig.git_clone_script(repos, token=None)

        assert "GIT_TOKEN" not in result
        assert "GIT_ASKPASS" not in result
        assert "trap" not in result

    def test_git_clone_script_with_path(self) -> None:
        """Script includes destination path when specified."""
        repos = [{"url": "https://github.com/user/repo.git", "path": "my-dir"}]
        result = WorkspaceConfig.git_clone_script(repos)

        assert "git clone https://github.com/user/repo.git my-dir" in result

"""Workspace configuration helpers for generating common config file content."""

import json
import shlex
from typing import Any


class WorkspaceConfig:
    """Helper class to generate common configuration file content for sandbox-agent SDK.

    This class provides static methods to generate JSON/JSONC configuration content
    for various tools used within sandbox workspaces.
    """

    @staticmethod
    def auth_json(credentials: dict[str, str]) -> str:
        """Generate auth.json content for oh-my-openagent.

        Args:
            credentials: Dictionary containing API keys (e.g.,
                {"openai_api_key": "sk-xxx", "anthropic_api_key": "sk-ant-..."})

        Returns:
            JSON string with credentials formatted for auth.json

        Example:
            >>> auth_content = WorkspaceConfig.auth_json({
            ...     "openai_api_key": "sk-...",
            ...     "anthropic_api_key": "sk-ant-..."
            ... })
        """
        return json.dumps(credentials, indent=2)

    @staticmethod
    def oh_my_openagent_config(
        models: list[dict[str, Any]],
        fallback_strategy: str = "round_robin"
    ) -> str:
        """Generate oh-my-openagent.jsonc content.

        Args:
            models: List of model configuration dictionaries, each containing
                provider and model information (e.g.,
                [{"provider": "openai", "model": "gpt-4"}])
            fallback_strategy: Strategy to use when primary model fails.
                Defaults to "round_robin".

        Returns:
            JSONC string (JSON with comments) containing models array and fallback_strategy

        Example:
            >>> omo_content = WorkspaceConfig.oh_my_openagent_config(
            ...     models=[
            ...         {"provider": "openai", "model": "gpt-4"},
            ...         {"provider": "anthropic", "model": "claude-3-sonnet"}
            ...     ],
            ...     fallback_strategy="round_robin"
            ... )
        """
        config = {
            "models": models,
            "fallback_strategy": fallback_strategy
        }
        json_content = json.dumps(config, indent=2)

        # Add comment header explaining the file
        comment_header = """// oh-my-openagent configuration file
// This file configures model routing and fallback strategies for the oh-my-openagent harness.
// Models are tried in order according to the fallback_strategy when requests fail.
//
// fallback_strategy options:
//   - "round_robin": Cycle through models in order
//   - "priority": Always try primary first, only fallback on failure
//
"""
        return comment_header + json_content

    @staticmethod
    def opencode_config(settings: dict[str, Any]) -> str:
        """Generate opencode.json content.

        Args:
            settings: Dictionary containing opencode configuration settings

        Returns:
            JSON string formatted for opencode.json

        Example:
            >>> opencode_content = WorkspaceConfig.opencode_config({
            ...     "default_agent": "claude",
            ...     "timeout_seconds": 300
            ... })
        """
        return json.dumps(settings, indent=2)

    @staticmethod
    def from_files(files: dict[str, str]) -> dict[str, str]:
        """Pass-through helper for workspace file dictionaries.

        This method provides type hints and validation for workspace file
        dictionaries, ensuring filename-to-content mappings are properly
        structured.

        Args:
            files: Dictionary mapping filenames to their content strings

        Returns:
            The same dictionary (pass-through)

        Example:
            >>> files = WorkspaceConfig.from_files({
            ...     "auth.json": auth_content,
            ...     "oh-my-openagent.jsonc": omo_content
            ... })
            >>> agent = await SandboxAgent.start(workspace_files=files)
        """
        return files

    @staticmethod
    def git_askpass_script(token: str) -> str:
        """Generate a GIT_ASKPASS script content.

        Note:
            The token parameter is accepted for API consistency but the generated
            script reads the token from the GIT_TOKEN environment variable for
            security (avoiding embedding credentials in the script itself).

        Args:
            token: The git authentication token (PAT). Must be exported as
                GIT_TOKEN environment variable when the script runs.

        Returns:
            Shell script content suitable for GIT_ASKPASS.

        Example:
            >>> script = WorkspaceConfig.git_askpass_script("ghp_xxx")
            >>> # Use with: export GIT_TOKEN="ghp_xxx" && export GIT_ASKPASS=script_path
        """
        return """#!/bin/sh
case "$1" in
  Username*) echo "git" ;;
  Password*) echo "$GIT_TOKEN" ;;
esac
"""

    @staticmethod
    def git_clone_script(
        repos: list[dict[str, Any]],
        token: str | None = None
    ) -> str:
        """Generate a shell script to clone multiple repositories.

        Args:
            repos: List of repo configs, each with:
                - url: str (required) - Git HTTPS URL
                - path: str (optional) - Destination path
                - branch: str (optional) - Branch to clone
                - depth: int (optional) - Shallow clone depth
            token: Optional authentication token for private repos.

        Returns:
            Shell script content that clones all repositories.

        Example:
            >>> repos = [
            ...     {"url": "https://github.com/owner/repo1.git", "path": "/workspace/r1"},
            ...     {"url": "https://github.com/owner/repo2.git", "branch": "dev", "depth": 1}
            ... ]
            >>> script = WorkspaceConfig.git_clone_script(repos, token="ghp_xxx")
        """
        lines: list[str] = [
            "#!/bin/sh",
            "set -euo pipefail",
            "",
        ]

        if token is not None:
            askpass_content = WorkspaceConfig.git_askpass_script(token).strip()
            if askpass_content.startswith("#!/"):
                askpass_content = "\n".join(askpass_content.split("\n")[1:]).strip()

            lines.extend([
                "cat << 'EOF' > ~/.git-askpass",
                askpass_content,
                "EOF",
                "chmod +x ~/.git-askpass",
                "export GIT_ASKPASS=~/.git-askpass",
                f"export GIT_TOKEN={shlex.quote(token)}",
                "export GIT_TERMINAL_PROMPT=0",
                'trap "rm -f ~/.git-askpass" EXIT',
                "",
            ])

        for repo in repos:
            url = repo["url"]
            path = repo.get("path")
            branch = repo.get("branch")
            depth = repo.get("depth")

            cmd_parts = ["git", "clone"]
            if branch is not None:
                cmd_parts.extend(["--branch", str(branch)])
            if depth is not None:
                cmd_parts.extend(["--depth", str(depth)])
            cmd_parts.append(url)
            if path is not None:
                cmd_parts.append(path)

            cmd = " ".join(cmd_parts)
            lines.append(f'{cmd} || echo "Error: failed to clone {url}" >&2')

        return "\n".join(lines) + "\n"

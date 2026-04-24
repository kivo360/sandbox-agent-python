"""AgentComputer provider — AgentComputer.ai integration."""

from __future__ import annotations

import os
from typing import Any, Callable

from sandboxagent.client import SandboxDestroyedError
from sandboxagent.providers.types import SandboxProvider

DEFAULT_API_URL = os.environ.get("COMPUTER_API_URL") or os.environ.get("AGENTCOMPUTER_API_URL") or "https://api.computer.agentcomputer.ai"
DEFAULT_POLL_INTERVAL_MS = 1_500
DEFAULT_START_TIMEOUT_MS = 300_000
DEFAULT_CWD = "/home/node"
BROWSER_ACCESS_REFRESH_SKEW_MS = 30_000
BROWSER_SESSION_COOKIE = "agentcomputer_access_session"

READY_STATUSES = {"starting", "running"}
FAILED_STATUSES = {"deleted", "error", "stopped", "stopping"}


class AgentComputerCreateOverrides:
    """Overrides for AgentComputer sandbox creation."""

    def __init__(
        self,
        handle: str | None = None,
        display_name: str | None = None,
        runtime_family: str | None = None,
        source_kind: str | None = None,
        image_family: str | None = None,
        image_ref: str | None = None,
        source_repo_url: str | None = None,
        source_ref: str | None = None,
        source_commit_sha: str | None = None,
        source_subpath: str | None = None,
        primary_port: int | None = None,
        primary_path: str | None = None,
        healthcheck_type: str | None = None,
        healthcheck_value: str | None = None,
        ssh_enabled: bool | None = None,
        vnc_enabled: bool | None = None,
        workspace_name: str | None = None,
        use_platform_default: bool | None = None,
        idea: str | None = None,
        initial_prompt: str | None = None,
    ) -> None:
        self.handle = handle
        self.display_name = display_name
        self.runtime_family = runtime_family
        self.source_kind = source_kind
        self.image_family = image_family
        self.image_ref = image_ref
        self.source_repo_url = source_repo_url
        self.source_ref = source_ref
        self.source_commit_sha = source_commit_sha
        self.source_subpath = source_subpath
        self.primary_port = primary_port
        self.primary_path = primary_path
        self.healthcheck_type = healthcheck_type
        self.healthcheck_value = healthcheck_value
        self.ssh_enabled = ssh_enabled
        self.vnc_enabled = vnc_enabled
        self.workspace_name = workspace_name
        self.use_platform_default = use_platform_default
        self.idea = idea
        self.initial_prompt = initial_prompt


class AgentComputerProviderOptions:
    """Options for the AgentComputer provider.

    Attributes:
        api_key: API key for AgentComputer (or env var COMPUTER_API_KEY).
        api_url: Base URL for the AgentComputer API.
        fetch: Custom fetch implementation.
        create: Overrides for sandbox creation.
        poll_interval_ms: Polling interval for status checks.
        start_timeout_ms: Timeout for sandbox startup.
        default_cwd: Default working directory.
    """

    def __init__(
        self,
        api_key: str | Callable[[], str] | None = None,
        api_url: str | None = None,
        fetch: Callable[..., Any] | None = None,
        create: AgentComputerCreateOverrides | Callable[[], AgentComputerCreateOverrides] | None = None,
        poll_interval_ms: int | None = None,
        start_timeout_ms: int | None = None,
        default_cwd: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.fetch = fetch
        self.create = create
        self.poll_interval_ms = poll_interval_ms
        self.start_timeout_ms = start_timeout_ms
        self.default_cwd = default_cwd


class AgentComputerApiError(Exception):
    """Error from AgentComputer API."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.name = "AgentComputerApiError"
        self.status = status


class AgentComputerProvider(SandboxProvider):
    """Provider for AgentComputer.ai sandboxes."""

    def __init__(self, options: AgentComputerProviderOptions | None = None) -> None:
        self.options = options or AgentComputerProviderOptions()
        self.api_url = self._normalize_api_url(self.options.api_url or DEFAULT_API_URL)
        self.poll_interval_ms = self.options.poll_interval_ms or DEFAULT_POLL_INTERVAL_MS
        self.start_timeout_ms = self.options.start_timeout_ms or DEFAULT_START_TIMEOUT_MS
        self._default_cwd = self.options.default_cwd or DEFAULT_CWD

        self._connection_url_by_sandbox: dict[str, str] = {}
        self._browser_access_by_sandbox: dict[str, dict[str, Any]] = {}
        self._ready_sandboxes: set[str] = set()

    @property
    def name(self) -> str:
        return "agentcomputer"

    @property
    def default_cwd(self) -> str | None:
        return self._default_cwd

    async def create(self) -> str:
        """Create a new AgentComputer sandbox."""
        create_options = await self._resolve_create_options(self.options.create)

        serialized_options = {
            "runtime_family": "managed-worker",
            "use_platform_default": True,
            **{k: v for k, v in create_options.items() if v is not None},
        }
        if self.env:
            serialized_options["env"] = {**(serialized_options.get("env") or {}), **self.env}

        computer = await self._api_request(
            "/v1/computers",
            {
                "method": "POST",
                "body": self._serialize_create_options(serialized_options),
            },
        )

        if not computer or not computer.get("id"):
            raise RuntimeError("agentcomputer create response did not return a computer id.")

        await self._wait_until_browser_ready(computer["id"])
        return computer["id"]

    async def destroy(self, sandbox_id: str) -> None:
        """Delete the AgentComputer sandbox."""
        self._browser_access_by_sandbox.pop(sandbox_id, None)
        self._connection_url_by_sandbox.pop(sandbox_id, None)
        self._ready_sandboxes.discard(sandbox_id)
        await self._api_request(
            f"/v1/computers/{sandbox_id}",
            {"method": "DELETE"},
            allow_not_found=True,
        )

    async def reconnect(self, sandbox_id: str) -> None:
        """Reconnect to an existing AgentComputer sandbox."""
        try:
            computer = await self._get_computer(sandbox_id, allow_not_found=True)
            if not computer:
                raise SandboxDestroyedError(sandbox_id, "agentcomputer")

            if self._is_ready_status(computer.get("status")):
                self._ready_sandboxes.add(sandbox_id)
                return

            if self._is_failed_status(computer.get("status")):
                self._ready_sandboxes.discard(sandbox_id)
                raise self._format_computer_status_error(sandbox_id, computer)
        except AgentComputerApiError as error:
            if error.status == 404:
                raise SandboxDestroyedError(sandbox_id, "agentcomputer")
            raise

    async def get_url(self, sandbox_id: str) -> str:
        """Get the connection URL for the AgentComputer sandbox."""
        return await self._get_connection_url(sandbox_id)

    async def get_fetch(self, sandbox_id: str) -> Callable[..., Any]:
        """Get a fetch function for the AgentComputer sandbox."""
        fetcher = self._resolve_fetch()

        async def fetch(input: str, init: dict[str, Any] | None = None) -> Any:
            init = init or {}
            sandbox_origin = self._get_origin(await self._get_connection_url(sandbox_id))
            request_origin = self._get_origin(input, sandbox_origin)

            if request_origin != sandbox_origin:
                return await fetcher(input, init)

            browser_access = await self._ensure_browser_access(sandbox_id)
            headers = dict(init.get("headers", {}))
            headers["cookie"] = self._merge_cookie_header(
                headers.get("cookie"), BROWSER_SESSION_COOKIE, browser_access["access_token"]
            )

            response = await fetcher(
                input,
                {**init, "headers": headers, "redirect": "manual"},
            )

            if response.status == 401 or self._is_auth_redirect(response):
                self._browser_access_by_sandbox.pop(sandbox_id, None)

            return response

        return fetch

    async def get_inspector_url(self, sandbox_id: str, base_url: str | None = None) -> str:
        """Get the Inspector URL for the AgentComputer sandbox."""
        browser_access = await self._ensure_browser_access(sandbox_id)
        return browser_access["inspector_url"]

    async def ensure_server(self, sandbox_id: str) -> None:
        """Ensure the sandbox-agent server is running.

        Managed-worker images already boot sandbox-agent and expose health on /v1/health.
        """
        pass

    async def _api_request(
        self, path: str, init: dict[str, Any] | None = None, allow_not_found: bool = False
    ) -> Any:
        """Make an API request to AgentComputer."""
        import httpx

        init = init or {}
        headers = dict(init.get("headers", {}))

        if "accept" not in headers:
            headers["accept"] = "application/json"
        if init.get("body") is not None and "content-type" not in headers:
            headers["content-type"] = "application/json"
        headers["authorization"] = f"Bearer {await self._resolve_api_key()}"

        fetcher = self._resolve_fetch()

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=init.get("method", "GET"),
                url=f"{self.api_url}{path}",
                headers=headers,
                content=init.get("body"),
            )

        if not response.is_success:
            if allow_not_found and response.status_code == 404:
                return None
            raise AgentComputerApiError(response.status_code, await self._read_error_message(response))

        if response.status_code == 204:
            return None

        return response.json()

    async def _get_computer(self, sandbox_id: str, allow_not_found: bool = False) -> dict[str, Any] | None:
        """Get computer information."""
        return await self._api_request(
            f"/v1/computers/{sandbox_id}",
            allow_not_found=allow_not_found,
        )

    async def _wait_until_browser_ready(self, sandbox_id: str) -> dict[str, Any]:
        """Wait until the computer is browser-ready."""
        import asyncio

        if sandbox_id in self._ready_sandboxes:
            return {"id": sandbox_id, "status": "running"}

        started_at = asyncio.get_event_loop().time()

        while True:
            computer = await self._get_computer(sandbox_id, allow_not_found=True)
            if not computer:
                raise SandboxDestroyedError(sandbox_id, "agentcomputer")

            if self._is_ready_status(computer.get("status")):
                self._ready_sandboxes.add(sandbox_id)
                return computer

            if self._is_failed_status(computer.get("status")):
                self._ready_sandboxes.discard(sandbox_id)
                raise self._format_computer_status_error(sandbox_id, computer)

            elapsed = (asyncio.get_event_loop().time() - started_at) * 1000
            if elapsed >= self.start_timeout_ms:
                raise RuntimeError(
                    f"agentcomputer computer '{sandbox_id}' did not become browser-ready within {self.start_timeout_ms}ms."
                )

            await asyncio.sleep(self.poll_interval_ms / 1000)

    async def _get_connection_url(self, sandbox_id: str) -> str:
        """Get the connection URL for a sandbox."""
        cached = self._connection_url_by_sandbox.get(sandbox_id)
        if cached:
            return cached

        response = await self._api_request(f"/v1/computers/{sandbox_id}/connection")
        web_url = response.get("connection", {}).get("web_url", "").strip()

        if not web_url:
            raise RuntimeError(f"agentcomputer connection info did not return a web_url for '{sandbox_id}'.")

        self._connection_url_by_sandbox[sandbox_id] = web_url
        return web_url

    async def _mint_browser_access(self, sandbox_id: str) -> dict[str, Any]:
        """Mint new browser access credentials."""
        await self._wait_until_browser_ready(sandbox_id)

        response = await self._api_request(
            f"/v1/computers/{sandbox_id}/access/browser",
            {"method": "POST"},
        )

        access_url = response.get("access_url", "").strip()
        if not access_url:
            raise RuntimeError(f"agentcomputer browser access did not return an access_url for '{sandbox_id}'.")

        state = self._parse_browser_access(access_url, response.get("expires_at"))
        self._browser_access_by_sandbox[sandbox_id] = state
        return state

    async def _ensure_browser_access(self, sandbox_id: str) -> dict[str, Any]:
        """Ensure valid browser access credentials."""
        cached = self._browser_access_by_sandbox.get(sandbox_id)
        if cached and not self._should_refresh_browser_access(cached):
            return cached
        return await self._mint_browser_access(sandbox_id)

    async def _resolve_api_key(self) -> str:
        """Resolve the API key from options or environment."""
        raw = self.options.api_key if not callable(self.options.api_key) else await self.options.api_key()
        api_key = (raw or os.environ.get("COMPUTER_API_KEY") or os.environ.get("AGENTCOMPUTER_API_KEY") or "").strip()

        if not api_key:
            raise RuntimeError("agentcomputer provider requires an API key. Set COMPUTER_API_KEY or pass `api_key`.")

        return api_key

    async def _resolve_create_options(
        self, value: AgentComputerCreateOverrides | Callable[[], AgentComputerCreateOverrides] | None
    ) -> dict[str, Any]:
        """Resolve create options."""
        if value is None:
            return {}
        if callable(value):
            import inspect

            result = await value() if inspect.iscoroutinefunction(value) else value()
            return {k: v for k, v in result.__dict__.items() if v is not None}
        return {k: v for k, v in value.__dict__.items() if v is not None}

    def _resolve_fetch(self) -> Callable[..., Any]:
        """Resolve the fetch implementation."""
        import httpx

        return self.options.fetch or (lambda **kwargs: httpx.AsyncClient().request(**kwargs))

    def _normalize_api_url(self, url: str) -> str:
        """Normalize the API URL."""
        return url.rstrip("/")

    def _serialize_create_options(self, options: dict[str, Any]) -> str:
        """Serialize create options to JSON."""
        import json

        mapping = {
            "handle": "handle",
            "display_name": "displayName",
            "runtime_family": "runtimeFamily",
            "source_kind": "sourceKind",
            "image_family": "imageFamily",
            "image_ref": "imageRef",
            "source_repo_url": "sourceRepoUrl",
            "source_ref": "sourceRef",
            "source_commit_sha": "sourceCommitSha",
            "source_subpath": "sourceSubpath",
            "primary_port": "primaryPort",
            "primary_path": "primaryPath",
            "healthcheck_type": "healthcheckType",
            "healthcheck_value": "healthcheckValue",
            "ssh_enabled": "sshEnabled",
            "vnc_enabled": "vncEnabled",
            "workspace_name": "workspaceName",
            "use_platform_default": "usePlatformDefault",
            "idea": "idea",
            "initial_prompt": "initialPrompt",
            "env": "env",
        }

        serialized = {}
        for api_key, attr_key in mapping.items():
            value = options.get(attr_key)
            if value is not None:
                serialized[api_key] = value

        return json.dumps(serialized)

    async def _read_error_message(self, response: Any) -> str:
        """Read error message from response."""
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
                if payload.get("error"):
                    return payload["error"]
                return str(payload)
            except Exception:
                return response.status_text or "request failed"

        return await response.text() or response.status_text or "request failed"

    def _is_ready_status(self, status: str | None) -> bool:
        """Check if status is ready."""
        return status in READY_STATUSES

    def _is_failed_status(self, status: str | None) -> bool:
        """Check if status is failed."""
        return status in FAILED_STATUSES

    def _format_computer_status_error(self, sandbox_id: str, computer: dict[str, Any]) -> Exception:
        """Format an error for computer status."""
        status = computer.get("status", "unknown")
        if status == "deleted":
            return SandboxDestroyedError(sandbox_id, "agentcomputer")

        suffix = f": {computer.get('last_error')}" if computer.get("last_error") else ""
        return RuntimeError(f"agentcomputer computer '{sandbox_id}' is not available (status '{status}'{suffix}).")

    def _get_origin(self, url: str, default: str | None = None) -> str:
        """Get the origin from a URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            if default:
                parsed = urlparse(default)
            else:
                return ""
        return f"{parsed.scheme}://{parsed.netloc}"

    def _merge_cookie_header(self, existing: str | None, name: str, value: str) -> str:
        """Merge a cookie into the header."""
        if not existing or not existing.strip():
            return f"{name}={value}"
        return f"{existing}; {name}={value}"

    def _is_auth_redirect(self, response: Any) -> bool:
        """Check if response is an auth redirect."""
        if response.status < 300 or response.status >= 400:
            return False
        location = response.headers.get("location", "")
        return "/login" in location or "auth_required" in location or "machine_unauthorized" in location

    def _parse_browser_access(self, access_url: str, expires_at_raw: str | None) -> dict[str, Any]:
        """Parse browser access response."""
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(access_url)
        params = parse_qs(parsed.query)

        access_token = params.get("access_token", [""])[0] or params.get("token", [""])[0]
        if not access_token:
            raise RuntimeError("agentcomputer browser access response did not include an access token.")

        inspector_url = f"{parsed.scheme}://{parsed.netloc}/ui/"
        expires_at = 0
        if expires_at_raw:
            try:
                from datetime import datetime

                expires_at = int(datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass

        return {
            "access_token": access_token,
            "inspector_url": inspector_url,
            "expires_at": expires_at,
        }

    def _should_refresh_browser_access(self, state: dict[str, Any]) -> bool:
        """Check if browser access should be refreshed."""
        import time

        return state["expires_at"] <= (time.time() * 1000) + BROWSER_ACCESS_REFRESH_SKEW_MS


def agentcomputer(options: AgentComputerProviderOptions | None = None) -> AgentComputerProvider:
    """Create an AgentComputer provider instance.

    Args:
        options: Configuration options for the AgentComputer provider.

    Returns:
        A configured AgentComputerProvider instance.
    """
    return AgentComputerProvider(options)

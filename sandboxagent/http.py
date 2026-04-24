"""HTTP transport layer for sandbox-agent API communication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

import httpx

from sandboxagent.types import ProblemDetails

T = TypeVar("T")

API_PREFIX = "/v1"
FS_PATH = f"{API_PREFIX}/fs"


class SandboxAgentError(Exception):
    """Error raised when a sandbox-agent API request fails."""

    def __init__(
        self,
        status: int,
        problem: ProblemDetails | dict[str, Any] | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        if isinstance(problem, ProblemDetails):
            title = problem.title
        elif isinstance(problem, dict):
            title = problem.get("title", f"Request failed with status {status}")
        else:
            title = f"Request failed with status {status}"
        super().__init__(title)
        self.status = status
        self.problem = problem
        self.response = response


class HttpTransport:
    """Low-level HTTP transport for sandbox-agent REST API.

    Wraps httpx.AsyncClient with sandbox-agent-specific error handling.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        default_headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if headers:
            default_headers.update(headers)

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=default_headers,
            timeout=timeout,
        )
        self._token = token

    def _apply_auth(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Apply authentication to request kwargs."""
        if self._token:
            headers = dict(kwargs.get("headers", {}))
            headers["Authorization"] = f"Bearer {self._token}"
            kwargs["headers"] = headers
        return kwargs

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """Send a GET request."""
        kwargs = self._apply_auth({"params": _flatten_params(params)})
        response = await self._client.get(path, **kwargs)
        return _check_response(response)

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send a POST request."""
        kwargs = self._apply_auth({})
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if params:
            kwargs["params"] = _flatten_params(params)
        response = await self._client.post(path, **kwargs)
        return _check_response(response)

    async def put(
        self,
        path: str,
        *,
        content: bytes | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send a PUT request."""
        kwargs = self._apply_auth({})
        if content is not None:
            kwargs["content"] = content
        if json is not None:
            kwargs["json"] = json
        if params:
            kwargs["params"] = _flatten_params(params)
        response = await self._client.put(path, **kwargs)
        return _check_response(response)

    async def delete(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """Send a DELETE request."""
        kwargs = self._apply_auth({"params": _flatten_params(params)})
        response = await self._client.delete(path, **kwargs)
        return _check_response(response)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        """Access the raw httpx client for advanced use cases."""
        return self._client


def _check_response(response: httpx.Response) -> httpx.Response:
    """Check response status and raise SandboxAgentError on failure."""
    if response.status_code >= 400:
        problem: ProblemDetails | dict[str, Any] | None = None
        try:
            data = response.json()
            try:
                problem = ProblemDetails.model_validate(data)
            except Exception:
                problem = data
        except Exception:
            pass
        raise SandboxAgentError(
            status=response.status_code,
            problem=problem,
            response=response,
        )
    return response


def _flatten_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten query parameters, converting lists and removing None values."""
    if not params:
        return {}
    flat: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            flat[key] = str(value).lower()
        elif isinstance(value, (list, tuple)):
            flat[key] = ",".join(str(v) for v in value)
        else:
            flat[key] = value
    return flat

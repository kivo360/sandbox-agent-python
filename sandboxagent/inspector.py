"""Build URLs to the sandbox-agent inspector UI."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode


def build_inspector_url(
    base_url: str,
    *,
    token: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Build a URL to the sandbox-agent inspector UI with connection parameters.

    The inspector UI is served at /ui/ on the sandbox-agent server.

    Args:
        base_url: Base URL of the sandbox-agent server.
        token: Optional bearer token for authentication.
        headers: Optional extra headers (JSON-encoded in the URL).

    Returns:
        Full inspector URL with query parameters.
    """
    normalized = base_url.rstrip("/")
    params: dict[str, str] = {}

    if token:
        params["token"] = token

    if headers and len(headers) > 0:
        import json
        params["headers"] = json.dumps(dict(headers))

    query = urlencode(params)
    return f"{normalized}/ui/{f'?{query}' if query else ''}"

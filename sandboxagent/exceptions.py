"""Exception classes for the Sandbox Agent SDK."""

from __future__ import annotations


class SandboxDestroyedError(Exception):
    """Raised when the sandbox no longer exists."""

    def __init__(self, sandbox_id: str, provider: str) -> None:
        super().__init__(f"Sandbox '{provider}/{sandbox_id}' no longer exists and cannot be reconnected.")
        self.sandbox_id = sandbox_id
        self.provider = provider


class UnsupportedSessionCategoryError(Exception):
    """Raised when a session does not support the requested category."""

    def __init__(self, session_id: str, category: str, available_categories: list[str]) -> None:
        cats = ", ".join(available_categories) or "(none)"
        super().__init__(f"Session '{session_id}' does not support category '{category}'. Available: {cats}")
        self.session_id = session_id
        self.category = category
        self.available_categories = available_categories


class UnsupportedSessionValueError(Exception):
    """Raised when a session does not support the requested value."""

    def __init__(
        self, session_id: str, category: str, config_id: str, requested_value: str, allowed_values: list[str]
    ) -> None:
        vals = ", ".join(allowed_values) or "(none)"
        super().__init__(
            f"Session '{session_id}' does not support value '{requested_value}' "
            f"for category '{category}' (configId='{config_id}'). Allowed: {vals}"
        )
        self.session_id = session_id
        self.category = category
        self.config_id = config_id
        self.requested_value = requested_value
        self.allowed_values = allowed_values


class UnsupportedSessionConfigOptionError(Exception):
    """Raised when a session does not expose the requested config option."""

    def __init__(self, session_id: str, config_id: str, available_config_ids: list[str]) -> None:
        ids = ", ".join(available_config_ids) or "(none)"
        super().__init__(f"Session '{session_id}' does not expose config option '{config_id}'. Available: {ids}")
        self.session_id = session_id
        self.config_id = config_id
        self.available_config_ids = available_config_ids


class UnsupportedPermissionReplyError(Exception):
    """Raised when a permission does not support the requested reply."""

    def __init__(self, permission_id: str, requested_reply: str, available_replies: list[str]) -> None:
        replies = ", ".join(available_replies) or "(none)"
        super().__init__(
            f"Permission '{permission_id}' does not support reply "
            f"'{requested_reply}'. Available: {replies}"
        )
        self.permission_id = permission_id
        self.requested_reply = requested_reply
        self.available_replies = available_replies


class DesktopNotSupportedError(Exception):
    """Raised when desktop streaming is not supported on the current platform.

    This typically occurs when the server returns HTTP 501 Not Implemented,
    indicating that desktop APIs are only available on Linux sandboxes.
    """

    def __init__(
        self,
        message: str = (
            "Desktop streaming is Unsupported on this platform. "
            "Only Linux sandboxes support desktop APIs."
        ),
    ) -> None:
        super().__init__(message)
        self.message = message

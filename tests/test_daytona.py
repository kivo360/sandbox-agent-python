from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from sandboxagent.providers.daytona import (
    DaytonaProvider,
    DaytonaProviderOptions,
    daytona,
    DEFAULT_AGENT_PORT,
    DEFAULT_CWD,
    DEFAULT_PREVIEW_TTL_SECONDS,
)


@pytest.fixture(autouse=True)
def mock_daytona_sdk():
    mock_module = MagicMock()
    mock_class = MagicMock()
    mock_instance = MagicMock()
    mock_class.return_value = mock_instance
    mock_module.Daytona = mock_class

    sys.modules["daytona_sdk"] = mock_module
    yield mock_instance
    del sys.modules["daytona_sdk"]


@pytest.fixture
def mock_sandbox():
    sandbox = MagicMock()
    sandbox.id = "test-sandbox-id"
    sandbox.delete = AsyncMock()
    sandbox.stop = AsyncMock()
    sandbox.start = AsyncMock()
    sandbox.process = MagicMock()
    sandbox.process.execute_command = AsyncMock()
    return sandbox


@pytest.fixture
def provider(mock_daytona_sdk):
    return DaytonaProvider()


class TestDaytonaProviderInit:
    def test_default_initialization(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        assert provider.agent_port == DEFAULT_AGENT_PORT
        assert provider.image == "rivetdev/sandbox-agent:0.5.0-rc.2-full"
        assert provider.cwd == DEFAULT_CWD
        assert provider.preview_ttl_seconds == DEFAULT_PREVIEW_TTL_SECONDS
        assert provider.options.delete_timeout_seconds is None

    def test_custom_options(self, mock_daytona_sdk):
        options = DaytonaProviderOptions(
            agent_port=8080,
            image="custom-image:latest",
            cwd="/custom/path",
            preview_ttl_seconds=3600,
            delete_timeout_seconds=60,
        )
        provider = DaytonaProvider(options)

        assert provider.agent_port == 8080
        assert provider.image == "custom-image:latest"
        assert provider.cwd == "/custom/path"
        assert provider.preview_ttl_seconds == 3600
        assert provider.options.delete_timeout_seconds == 60

    def test_name_property(self, mock_daytona_sdk):
        provider = DaytonaProvider()
        assert provider.name == "daytona"

    def test_default_cwd_property(self, mock_daytona_sdk):
        provider = DaytonaProvider()
        assert provider.default_cwd == DEFAULT_CWD

    def test_import_error_raises(self):
        original_module = sys.modules.pop("daytona_sdk", None)
        try:
            with pytest.raises(ImportError) as exc_info:
                DaytonaProvider()
            assert "daytona provider requires 'daytona-sdk' package" in str(exc_info.value)
        finally:
            if original_module:
                sys.modules["daytona_sdk"] = original_module


class TestDaytonaProviderCreate:
    async def test_create_success(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        sandbox_id = await provider.create()

        assert sandbox_id == "test-sandbox-id"
        mock_daytona_sdk.create.assert_called_once()
        call_kwargs = mock_daytona_sdk.create.call_args.kwargs
        assert call_kwargs["image"] == provider.image
        assert call_kwargs["auto_stop_interval"] == 0

    async def test_create_executes_server_command(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        await provider.create()

        mock_sandbox.process.execute_command.assert_called_once()
        command = mock_sandbox.process.execute_command.call_args[0][0]
        assert "sandbox-agent server" in command
        assert f"--port {DEFAULT_AGENT_PORT}" in command

    async def test_create_with_env_vars(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()
        provider.set_env({"FOO": "bar", "BAZ": "qux"})

        await provider.create()

        call_kwargs = mock_daytona_sdk.create.call_args.kwargs
        assert call_kwargs["envVars"] == {"FOO": "bar", "BAZ": "qux"}

    async def test_create_with_env_vars_and_existing_opts(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)
        options = DaytonaProviderOptions(create={"envVars": {"EXISTING": "value"}})
        provider = DaytonaProvider(options)
        provider.set_env({"FOO": "bar"})

        await provider.create()

        call_kwargs = mock_daytona_sdk.create.call_args.kwargs
        assert call_kwargs["envVars"] == {"EXISTING": "value", "FOO": "bar"}

    async def test_create_with_callable_options(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)
        options = DaytonaProviderOptions(create=lambda: {"custom": "value"})
        provider = DaytonaProvider(options)

        await provider.create()

        call_kwargs = mock_daytona_sdk.create.call_args.kwargs
        assert call_kwargs["custom"] == "value"

    async def test_create_with_async_callable_options(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.create = AsyncMock(return_value=mock_sandbox)

        async def async_opts() -> dict[str, Any]:
            return {"async_custom": "value"}

        options = DaytonaProviderOptions(create=async_opts)  # type: ignore
        provider = DaytonaProvider(options)

        await provider.create()

        call_kwargs = mock_daytona_sdk.create.call_args.kwargs
        assert call_kwargs["async_custom"] == "value"


class TestDaytonaProviderDestroy:
    async def test_destroy_success(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.get = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        await provider.destroy("test-sandbox-id")

        mock_daytona_sdk.get.assert_called_once_with("test-sandbox-id")
        mock_sandbox.delete.assert_called_once_with(None)

    async def test_destroy_with_timeout(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.get = AsyncMock(return_value=mock_sandbox)
        options = DaytonaProviderOptions(delete_timeout_seconds=120)
        provider = DaytonaProvider(options)

        await provider.destroy("test-sandbox-id")

        mock_sandbox.delete.assert_called_once_with(120)

    async def test_destroy_sandbox_not_found(self, mock_daytona_sdk):
        mock_daytona_sdk.get = AsyncMock(return_value=None)
        provider = DaytonaProvider()

        await provider.destroy("non-existent-id")

        mock_daytona_sdk.get.assert_called_once_with("non-existent-id")


class TestDaytonaProviderGetUrl:
    async def test_get_url_success_string_preview(self, mock_daytona_sdk, mock_sandbox):
        mock_sandbox.get_signed_preview_url = AsyncMock(return_value="https://preview.example.com")
        mock_daytona_sdk.get = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        url = await provider.get_url("test-sandbox-id")

        assert url == "https://preview.example.com"
        mock_sandbox.get_signed_preview_url.assert_called_once_with(
            DEFAULT_AGENT_PORT, DEFAULT_PREVIEW_TTL_SECONDS
        )

    async def test_get_url_success_object_preview(self, mock_daytona_sdk, mock_sandbox):
        preview_obj = MagicMock()
        preview_obj.url = "https://preview.example.com/object"
        mock_sandbox.get_signed_preview_url = AsyncMock(return_value=preview_obj)
        mock_daytona_sdk.get = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        url = await provider.get_url("test-sandbox-id")

        assert url == "https://preview.example.com/object"

    async def test_get_url_sandbox_not_found(self, mock_daytona_sdk):
        mock_daytona_sdk.get = AsyncMock(return_value=None)
        provider = DaytonaProvider()

        with pytest.raises(RuntimeError) as exc_info:
            await provider.get_url("non-existent-id")

        assert "daytona sandbox not found: non-existent-id" in str(exc_info.value)


class TestDaytonaProviderEnsureServer:
    async def test_ensure_server_success(self, mock_daytona_sdk, mock_sandbox):
        mock_daytona_sdk.get = AsyncMock(return_value=mock_sandbox)
        provider = DaytonaProvider()

        await provider.ensure_server("test-sandbox-id")

        mock_daytona_sdk.get.assert_called_once_with("test-sandbox-id")
        mock_sandbox.process.execute_command.assert_called_once()
        command = mock_sandbox.process.execute_command.call_args[0][0]
        assert "sandbox-agent server" in command

    async def test_ensure_server_sandbox_not_found(self, mock_daytona_sdk):
        mock_daytona_sdk.get = AsyncMock(return_value=None)
        provider = DaytonaProvider()

        with pytest.raises(RuntimeError) as exc_info:
            await provider.ensure_server("non-existent-id")

        assert "daytona sandbox not found: non-existent-id" in str(exc_info.value)


class TestDaytonaProviderInheritedMethods:
    async def test_pause_default_pass(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        result = await provider.pause("test-sandbox-id")

        assert result is None

    async def test_kill_default_pass(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        result = await provider.kill("test-sandbox-id")

        assert result is None

    async def test_reconnect_default_pass(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        result = await provider.reconnect("test-sandbox-id")

        assert result is None


class TestDaytonaProviderSetEnv:
    def test_set_env(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        provider.set_env({"KEY1": "value1", "KEY2": "value2"})

        assert provider.env == {"KEY1": "value1", "KEY2": "value2"}

    def test_set_env_overwrites(self, mock_daytona_sdk):
        provider = DaytonaProvider()

        provider.set_env({"OLD": "old_value"})
        provider.set_env({"NEW": "new_value"})

        assert provider.env == {"NEW": "new_value"}


class TestDaytonaFactoryFunction:
    def test_daytona_factory_with_defaults(self, mock_daytona_sdk):
        provider = daytona()

        assert isinstance(provider, DaytonaProvider)
        assert provider.agent_port == DEFAULT_AGENT_PORT

    def test_daytona_factory_with_options(self, mock_daytona_sdk):
        options = DaytonaProviderOptions(agent_port=9090)
        provider = daytona(options)

        assert provider.agent_port == 9090


class TestDaytonaProviderOptions:
    def test_options_defaults(self):
        opts = DaytonaProviderOptions()

        assert opts.create is None
        assert opts.image is None
        assert opts.agent_port is None
        assert opts.cwd is None
        assert opts.preview_ttl_seconds is None
        assert opts.delete_timeout_seconds is None

    def test_options_custom_values(self):
        opts = DaytonaProviderOptions(
            create={"key": "value"},
            image="test-image",
            agent_port=1234,
            cwd="/test",
            preview_ttl_seconds=1800,
            delete_timeout_seconds=30,
        )

        assert opts.create == {"key": "value"}
        assert opts.image == "test-image"
        assert opts.agent_port == 1234
        assert opts.cwd == "/test"
        assert opts.preview_ttl_seconds == 1800
        assert opts.delete_timeout_seconds == 30

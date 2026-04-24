"""Unit tests for WorkspaceConfig class."""

import json
from typing import Any

import pytest

from sandboxagent.workspace_config import WorkspaceConfig


class TestAuthJson:
    """Tests for WorkspaceConfig.auth_json method."""

    def test_auth_json_with_api_keys(self) -> None:
        """Test auth_json with typical API key credentials."""
        credentials = {
            "openai_api_key": "sk-test",
            "anthropic_api_key": "sk-ant-test"
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["openai_api_key"] == "sk-test"
        assert parsed["anthropic_api_key"] == "sk-ant-test"

    def test_auth_json_empty_dict(self) -> None:
        """Test auth_json with empty credentials dict."""
        result = WorkspaceConfig.auth_json({})
        parsed = json.loads(result)
        assert parsed == {}

    def test_auth_json_single_key(self) -> None:
        """Test auth_json with single API key."""
        credentials = {"openai_api_key": "sk-abc123"}
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["openai_api_key"] == "sk-abc123"

    def test_auth_json_special_characters(self) -> None:
        """Test auth_json handles special characters in values."""
        credentials = {
            "api_key": "sk-test!@#$%^&*()_+-=[]{}|;':\",./<>?",
            "special": "value\nwith\ttabs"
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["api_key"] == credentials["api_key"]
        assert parsed["special"] == credentials["special"]

    def test_auth_json_unicode(self) -> None:
        """Test auth_json handles unicode characters."""
        credentials = {
            "api_key": "sk-测试密钥",
            "emoji_key": "sk-🔑🚀"
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["api_key"] == "sk-测试密钥"
        assert parsed["emoji_key"] == "sk-🔑🚀"

    def test_auth_json_nested_values(self) -> None:
        """Test auth_json with nested dictionary values."""
        credentials: dict[str, Any] = {
            "openai": {"api_key": "sk-test", "org_id": "org-123"},
            "anthropic": {"api_key": "sk-ant-test"}
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["openai"]["api_key"] == "sk-test"
        assert parsed["openai"]["org_id"] == "org-123"
        assert parsed["anthropic"]["api_key"] == "sk-ant-test"

    def test_auth_json_list_values(self) -> None:
        """Test auth_json with list values."""
        credentials: dict[str, Any] = {
            "api_keys": ["sk-1", "sk-2", "sk-3"],
            "primary": "sk-main"
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["api_keys"] == ["sk-1", "sk-2", "sk-3"]
        assert parsed["primary"] == "sk-main"

    def test_auth_json_boolean_and_null(self) -> None:
        """Test auth_json with boolean and null values."""
        credentials: dict[str, Any] = {
            "enabled": True,
            "disabled": False,
            "optional": None
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["enabled"] is True
        assert parsed["disabled"] is False
        assert parsed["optional"] is None

    def test_auth_json_numeric_values(self) -> None:
        """Test auth_json with numeric values."""
        credentials: dict[str, Any] = {
            "timeout": 30,
            "rate_limit": 100.5,
            "max_retries": 0
        }
        result = WorkspaceConfig.auth_json(credentials)
        parsed = json.loads(result)
        assert parsed["timeout"] == 30
        assert parsed["rate_limit"] == 100.5
        assert parsed["max_retries"] == 0

    def test_auth_json_output_is_valid_json(self) -> None:
        """Verify auth_json output is valid JSON."""
        credentials = {"key": "value"}
        result = WorkspaceConfig.auth_json(credentials)
        # Should not raise
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_auth_json_indentation(self) -> None:
        """Test auth_json produces indented output."""
        credentials = {"key": "value"}
        result = WorkspaceConfig.auth_json(credentials)
        # Should have 2-space indentation
        assert "  \"key\"" in result


class TestOhMyOpenagentConfig:
    """Tests for WorkspaceConfig.oh_my_openagent_config method."""

    def test_oh_my_openagent_config_default_strategy(self) -> None:
        """Test oh_my_openagent_config with default round_robin strategy."""
        models = [{"provider": "openai", "model": "gpt-4"}]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        assert "// oh-my-openagent configuration file" in result
        assert '"fallback_strategy": "round_robin"' in result

    def test_oh_my_openagent_config_custom_strategy(self) -> None:
        """Test oh_my_openagent_config with custom fallback strategy."""
        models = [{"provider": "openai", "model": "gpt-4"}]
        result = WorkspaceConfig.oh_my_openagent_config(models, fallback_strategy="priority")
        assert "// oh-my-openagent configuration file" in result
        assert '"fallback_strategy": "priority"' in result

    def test_oh_my_openagent_config_multiple_models(self) -> None:
        """Test oh_my_openagent_config with multiple models."""
        models = [
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3-sonnet"},
            {"provider": "google", "model": "gemini-pro"}
        ]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        assert '"provider": "openai"' in result
        assert '"provider": "anthropic"' in result
        assert '"provider": "google"' in result
        assert '"model": "gpt-4"' in result
        assert '"model": "claude-3-sonnet"' in result
        assert '"model": "gemini-pro"' in result

    def test_oh_my_openagent_config_empty_models(self) -> None:
        """Test oh_my_openagent_config with empty models list."""
        models: list[dict[str, Any]] = []
        result = WorkspaceConfig.oh_my_openagent_config(models)
        assert "// oh-my-openagent configuration file" in result
        assert '"models": []' in result

    def test_oh_my_openagent_config_model_with_extra_fields(self) -> None:
        """Test oh_my_openagent_config with models containing extra fields."""
        models = [
            {
                "provider": "openai",
                "model": "gpt-4",
                "temperature": 0.7,
                "max_tokens": 2000
            }
        ]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        assert '"temperature": 0.7' in result
        assert '"max_tokens": 2000' in result

    def test_oh_my_openagent_config_comment_header_present(self) -> None:
        """Verify comment header is present in output."""
        models = [{"provider": "openai", "model": "gpt-4"}]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        assert result.startswith("// oh-my-openagent configuration file")
        assert "// This file configures model routing" in result
        assert "// fallback_strategy options:" in result
        assert "//   - \"round_robin\"" in result
        assert "//   - \"priority\"" in result

    def test_oh_my_openagent_config_json_parseable(self) -> None:
        """Verify JSON portion is parseable after removing comments."""
        models = [{"provider": "openai", "model": "gpt-4"}]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        # Extract JSON portion (after the comment block)
        json_start = result.find("{")
        json_content = result[json_start:]
        parsed = json.loads(json_content)
        assert parsed["models"] == models
        assert parsed["fallback_strategy"] == "round_robin"

    def test_oh_my_openagent_config_special_chars_in_model(self) -> None:
        """Test handling of special characters in model names."""
        models = [{"provider": "custom", "model": "model-v1.5-beta"}]
        result = WorkspaceConfig.oh_my_openagent_config(models)
        json_start = result.find("{")
        json_content = result[json_start:]
        parsed = json.loads(json_content)
        assert parsed["models"][0]["model"] == "model-v1.5-beta"


class TestOpencodeConfig:
    """Tests for WorkspaceConfig.opencode_config method."""

    def test_opencode_config_basic(self) -> None:
        """Test opencode_config with basic settings."""
        settings = {
            "default_agent": "claude",
            "timeout_seconds": 300
        }
        result = WorkspaceConfig.opencode_config(settings)
        parsed = json.loads(result)
        assert parsed["default_agent"] == "claude"
        assert parsed["timeout_seconds"] == 300

    def test_opencode_config_empty_dict(self) -> None:
        """Test opencode_config with empty settings."""
        result = WorkspaceConfig.opencode_config({})
        parsed = json.loads(result)
        assert parsed == {}

    def test_opencode_config_nested(self) -> None:
        """Test opencode_config with nested settings."""
        settings = {
            "agents": {
                "claude": {"model": "claude-3-sonnet"},
                "gpt4": {"model": "gpt-4"}
            },
            "default": "claude"
        }
        result = WorkspaceConfig.opencode_config(settings)
        parsed = json.loads(result)
        assert parsed["agents"]["claude"]["model"] == "claude-3-sonnet"
        assert parsed["agents"]["gpt4"]["model"] == "gpt-4"
        assert parsed["default"] == "claude"

    def test_opencode_config_complex_types(self) -> None:
        """Test opencode_config with various complex types."""
        settings = {
            "enabled": True,
            "count": 42,
            "ratio": 0.95,
            "names": ["claude", "gpt", "gemini"],
            "config": None
        }
        result = WorkspaceConfig.opencode_config(settings)
        parsed = json.loads(result)
        assert parsed["enabled"] is True
        assert parsed["count"] == 42
        assert parsed["ratio"] == 0.95
        assert parsed["names"] == ["claude", "gpt", "gemini"]
        assert parsed["config"] is None

    def test_opencode_config_special_characters(self) -> None:
        """Test opencode_config with special characters."""
        settings = {
            "path": "/home/user/.config/opencode",
            "pattern": "*.py",
            "regex": "[a-z]+\\d*"
        }
        result = WorkspaceConfig.opencode_config(settings)
        parsed = json.loads(result)
        assert parsed["path"] == "/home/user/.config/opencode"
        assert parsed["pattern"] == "*.py"
        assert parsed["regex"] == "[a-z]+\\d*"

    def test_opencode_config_unicode(self) -> None:
        """Test opencode_config with unicode characters."""
        settings = {
            "name": "测试配置",
            "emoji": "🚀🔧⚙️"
        }
        result = WorkspaceConfig.opencode_config(settings)
        parsed = json.loads(result)
        assert parsed["name"] == "测试配置"
        assert parsed["emoji"] == "🚀🔧⚙️"

    def test_opencode_config_indentation(self) -> None:
        """Test opencode_config produces indented output."""
        settings = {"key": "value"}
        result = WorkspaceConfig.opencode_config(settings)
        assert "  \"key\"" in result

    def test_opencode_config_valid_json(self) -> None:
        """Verify opencode_config output is valid JSON."""
        settings = {"test": "value", "number": 123}
        result = WorkspaceConfig.opencode_config(settings)
        # Should not raise
        parsed = json.loads(result)
        assert isinstance(parsed, dict)


class TestFromFiles:
    """Tests for WorkspaceConfig.from_files method."""

    def test_from_files_pass_through(self) -> None:
        """Test from_files returns the same dictionary."""
        files = {
            "auth.json": '{"key": "value"}',
            "config.yaml": "setting: value"
        }
        result = WorkspaceConfig.from_files(files)
        assert result is files
        assert result["auth.json"] == '{"key": "value"}'
        assert result["config.yaml"] == "setting: value"

    def test_from_files_empty_dict(self) -> None:
        """Test from_files with empty dictionary."""
        files: dict[str, str] = {}
        result = WorkspaceConfig.from_files(files)
        assert result == {}
        assert result is files

    def test_from_files_single_file(self) -> None:
        """Test from_files with single file."""
        files = {"readme.md": "# Hello World"}
        result = WorkspaceConfig.from_files(files)
        assert result["readme.md"] == "# Hello World"

    def test_from_files_many_files(self) -> None:
        """Test from_files with many files."""
        files = {f"file_{i}.txt": f"content {i}" for i in range(100)}
        result = WorkspaceConfig.from_files(files)
        assert len(result) == 100
        assert result["file_0.txt"] == "content 0"
        assert result["file_99.txt"] == "content 99"

    def test_from_files_special_content(self) -> None:
        """Test from_files with special content characters."""
        files = {
            "special.json": '{"key": "value with \\"quotes\\""}',
            "multiline.txt": "line1\nline2\nline3",
            "unicode.txt": "日本語コンテンツ 🎌"
        }
        result = WorkspaceConfig.from_files(files)
        assert "quotes" in result["special.json"]
        assert "\n" in result["multiline.txt"]
        assert "日本語" in result["unicode.txt"]

    def test_from_files_empty_content(self) -> None:
        """Test from_files with empty content strings."""
        files = {
            "empty.txt": "",
            "nonempty.txt": "has content"
        }
        result = WorkspaceConfig.from_files(files)
        assert result["empty.txt"] == ""
        assert result["nonempty.txt"] == "has content"

    def test_from_files_preserves_order(self) -> None:
        """Test from_files preserves dictionary order."""
        files = {
            "z.txt": "last",
            "a.txt": "first",
            "m.txt": "middle"
        }
        result = WorkspaceConfig.from_files(files)
        # In Python 3.7+, dict preserves insertion order
        keys = list(result.keys())
        assert keys[0] == "z.txt"
        assert keys[1] == "a.txt"
        assert keys[2] == "m.txt"


class TestWorkspaceConfigEdgeCases:
    """Edge case tests across all WorkspaceConfig methods."""

    def test_auth_json_vs_opencode_config_same_input(self) -> None:
        """Verify both methods handle same input consistently."""
        data: dict[str, Any] = {"key": "value", "number": 42}
        auth_result = WorkspaceConfig.auth_json(data)
        opencode_result = WorkspaceConfig.opencode_config(data)
        # Both should produce valid JSON with same content
        auth_parsed = json.loads(auth_result)
        opencode_parsed = json.loads(opencode_result)
        assert auth_parsed == opencode_parsed

    def test_all_methods_handle_deeply_nested(self) -> None:
        """Test all methods handle deeply nested structures."""
        nested: dict[str, Any] = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {"value": "deep"}
                    }
                }
            }
        }
        # auth_json
        auth_result = json.loads(WorkspaceConfig.auth_json(nested))
        assert auth_result["level1"]["level2"]["level3"]["level4"]["value"] == "deep"

        # opencode_config
        opencode_result = json.loads(WorkspaceConfig.opencode_config(nested))
        assert opencode_result["level1"]["level2"]["level3"]["level4"]["value"] == "deep"

        # oh_my_openagent_config with nested model config
        models = [{"provider": "test", "config": nested}]
        omo_result = WorkspaceConfig.oh_my_openagent_config(models)
        json_start = omo_result.find("{")
        omo_parsed = json.loads(omo_result[json_start:])
        assert omo_parsed["models"][0]["config"]["level1"]["level2"]["level3"]["level4"]["value"] == "deep"

    def test_large_content(self) -> None:
        """Test methods handle large content."""
        large_content: str = "x" * 10000
        files: dict[str, str] = {"large.txt": large_content}
        result = WorkspaceConfig.from_files(files)
        assert len(result["large.txt"]) == 10000

        large_dict: dict[str, Any] = {"content": large_content}
        auth_result = json.loads(WorkspaceConfig.auth_json(large_dict))
        assert len(auth_result["content"]) == 10000

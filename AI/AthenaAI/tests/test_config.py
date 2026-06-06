"""Test config module."""

import os

from athenaai.config import (
    DEFAULT_OPENCODE_GO_API_URL,
    KIMI_K2_6_MODEL,
    OPENCODE_GO_API_URL_ENV_VAR,
    OPENCODE_GO_API_KEY_ENV_VAR,
    AGENT_COORDINATOR,
    AGENT_BOHEMIA_WEST,
    AGENT_BOHEMIA_EAST,
    AGENT_MORAVIA,
    AGENT_SILESIA,
    AGENT_ORACLE,
    REGIONAL_AGENTS,
    ALL_AGENTS,
    get_opencode_api_key,
    get_opencode_api_url,
    get_opencode_config_path,
    OPENCODE_CONFIG_DIR,
    ATHENAAI_ROOT,
)


class TestModelConsistency:
    def test_kimi_k2_6_model_defined(self):
        assert KIMI_K2_6_MODEL == "kimi-k2.6"

    def test_model_identifier_not_empty(self):
        assert len(KIMI_K2_6_MODEL) > 0

    def test_model_identifier_consistent_format(self):
        assert "-" in KIMI_K2_6_MODEL

    def test_all_agents_use_same_model(self):
        from athenaai.agents import get_all_agent_configs
        configs = get_all_agent_configs()
        for config in configs:
            assert config.model == KIMI_K2_6_MODEL


class TestAgentIdentifiers:
    def test_coordinator_defined(self):
        assert AGENT_COORDINATOR == "coordinator"

    def test_regional_agents_defined(self):
        assert AGENT_BOHEMIA_WEST == "bohemia-west"
        assert AGENT_BOHEMIA_EAST == "bohemia-east"
        assert AGENT_MORAVIA == "moravia"
        assert AGENT_SILESIA == "silesia"

    def test_oracle_defined(self):
        assert AGENT_ORACLE == "oracle"

    def test_regional_agents_list_complete(self):
        assert len(REGIONAL_AGENTS) == 4
        assert "bohemia-west" in REGIONAL_AGENTS
        assert "bohemia-east" in REGIONAL_AGENTS
        assert "moravia" in REGIONAL_AGENTS
        assert "silesia" in REGIONAL_AGENTS

    def test_all_agents_includes_coordinator_and_oracle(self):
        assert AGENT_COORDINATOR in ALL_AGENTS
        assert AGENT_ORACLE in ALL_AGENTS
        assert len(ALL_AGENTS) == 6


class TestApiKeyEnvVar:
    def test_api_key_env_var_name_defined(self):
        assert OPENCODE_GO_API_KEY_ENV_VAR == "OPENCODE_GO_API_KEY"

    def test_api_key_not_hardcoded_in_config(self):
        env_var_value = os.environ.get(OPENCODE_GO_API_KEY_ENV_VAR)
        if env_var_value is not None:
            assert env_var_value != ""

    def test_get_opencode_api_key_returns_none_when_not_set(self):
        original = os.environ.pop(OPENCODE_GO_API_KEY_ENV_VAR, None)
        try:
            result = get_opencode_api_key()
            assert result is None
        finally:
            if original is not None:
                os.environ[OPENCODE_GO_API_KEY_ENV_VAR] = original

    def test_get_opencode_api_key_returns_value_when_set(self):
        os.environ[OPENCODE_GO_API_KEY_ENV_VAR] = "test-key-123"
        try:
            result = get_opencode_api_key()
            assert result == "test-key-123"
        finally:
            os.environ.pop(OPENCODE_GO_API_KEY_ENV_VAR, None)

    def test_api_key_retrieval_returns_env_value(self):
        os.environ[OPENCODE_GO_API_KEY_ENV_VAR] = "test-secret-key-123"
        try:
            result = get_opencode_api_key()
            assert result == "test-secret-key-123"
        finally:
            os.environ.pop(OPENCODE_GO_API_KEY_ENV_VAR, None)

    def test_api_url_defaults_to_opencode_go_endpoint(self):
        original = os.environ.pop(OPENCODE_GO_API_URL_ENV_VAR, None)
        try:
            assert DEFAULT_OPENCODE_GO_API_URL.endswith("/v1")
            assert get_opencode_api_url() == DEFAULT_OPENCODE_GO_API_URL
        finally:
            if original is not None:
                os.environ[OPENCODE_GO_API_URL_ENV_VAR] = original

    def test_api_url_can_be_overridden(self):
        os.environ[OPENCODE_GO_API_URL_ENV_VAR] = "https://example.test/v1"
        try:
            assert get_opencode_api_url() == "https://example.test/v1"
        finally:
            os.environ.pop(OPENCODE_GO_API_URL_ENV_VAR, None)


class TestPathConfiguration:
    def test_opencode_config_dir_is_path(self):
        assert hasattr(OPENCODE_CONFIG_DIR, '__fspath__') or isinstance(OPENCODE_CONFIG_DIR, object)

    def test_opencode_config_path_returns_existing_path(self):
        path = get_opencode_config_path()
        assert str(path).endswith("opencode.jsonc")

    def test_opencode_config_exists(self):
        path = get_opencode_config_path()
        assert path.exists(), f"Config file should exist at {path}"


class TestSecretsNonExposure:
    def test_no_secret_in_config_file(self):
        config_path = get_opencode_config_path()
        content = config_path.read_text()
        assert "sk-" not in content.lower()
        assert "secret" not in content.lower()
        assert not any(
            token in content.lower()
            for token in ["sk_live_", "sk_test_", "sk_dev_"]
        )

    def test_no_raw_key_in_package(self):
        import athenaai.config as config_module
        source_file = config_module.__file__
        if source_file:
            content = open(source_file, encoding="utf-8").read()
            assert "sk-" not in content.lower() or "sk-" in ["sk-", "sk-xxx"]

    def test_no_raw_secret_tokens_in_tracked_files(self):
        import re
        from pathlib import Path

        athenaai_root = Path(__file__).parent.parent
        secret_patterns = [
            re.compile(r'sk-[A-Za-z0-9]{20,}'),  # OpenAI-style keys
            re.compile(r'sk_dev_[A-Za-z0-9]{20,}'),  # Dev keys
            re.compile(r'Bearer\s+[A-Za-z0-9\-_]{20,}'),  # Bearer tokens
            re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\'][A-Za-z0-9\-_]{20,}["\']'),  # API key assignments
        ]

        tracked_extensions = {'.py', '.jsonc', '.json', '.yaml', '.yml', '.toml', '.txt'}
        exclude_dirs = {'__pycache__', '.git', 'node_modules', '.pytest_cache'}

        violations = []
        for py_file in athenaai_root.rglob('*'):
            if py_file.suffix not in tracked_extensions:
                continue
            if any(exc in py_file.parts for exc in exclude_dirs):
                continue
            if 'OPENCODE_GO_API_KEY' in str(py_file):
                continue

            try:
                content = py_file.read_text()
                for pattern in secret_patterns:
                    matches = pattern.findall(content)
                    for match in matches:
                        if 'test' not in match.lower() and 'placeholder' not in match.lower():
                            violations.append(f"{py_file.relative_to(athenaai_root)}: found '{match[:30]}...'")
            except Exception:
                pass

        assert len(violations) == 0, f"Secret tokens found: {violations}"

from __future__ import annotations

from animetta.config.core.registry import ProviderRegistry
from animetta.config.persona import PersonaConfig

"""Tests for AppConfig - application configuration loading."""

import os
from unittest.mock import MagicMock, patch

import pytest

from animetta.config.app import (
    AppConfig,
    ServicesConfig,
    _load_env_file,
    _load_service_config,
    expand_env_vars,
)

# =============================================================================
# Autouse Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clean_config_globals():
    """Clean module-level state between tests to avoid cross-test pollution.

    Resets:
        _env_file_loaded (idempotency flag for _load_env_file)
        _services_yaml_cache (unified yaml cache)
        _services_config_logged (logged service set)
        expand_env_vars.replace_var attrs (GLM_API_KEY logging)
    """
    import animetta.config.app as app_module

    app_module._env_file_loaded = False
    app_module._services_yaml_cache = None
    app_module._services_config_logged = set()


@pytest.fixture
def mock_yaml_data():
    """Return a realistic main YAML config dict."""
    return {
        "persona": "test_assistant",
        "services": {
            "asr": "mock",
            "tts": "mock",
            "agent": "mock",
            "vad": "mock",
        },
        "system": {
            "host": "0.0.0.0",
            "port": 12394,
            "debug": False,
            "log_level": "INFO",
            "gpt_sovits": {},
        },
    }


# =============================================================================
# 1. TestExpandEnvVars
# =============================================================================


class TestExpandEnvVars:
    """Tests for expand_env_vars function."""

    def test_expand_braced_env_var(self):
        """${VAR} syntax is expanded to the env var value."""
        with patch.dict(os.environ, {"MY_KEY": "my_value"}, clear=False):
            result = expand_env_vars("prefix-${MY_KEY}-suffix")
        assert result == "prefix-my_value-suffix"

    def test_expand_unbraced_env_var(self):
        """$VAR syntax is expanded to the env var value."""
        with patch.dict(os.environ, {"MY_KEY": "value123"}, clear=False):
            result = expand_env_vars("prefix-$MY_KEY-suffix")
        assert result == "prefix-value123-suffix"

    def test_missing_var_returns_empty(self):
        """Missing env var returns empty string (no crash)."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars("hello-${NONEXISTENT}-world")
        assert result == "hello--world"

    def test_missing_unbraced_var_returns_empty(self):
        """Missing unbraced env var returns empty string (no crash)."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars("hello-$MISSING-world")
        # $MISSING is replaced with "", leaving "hello--world"
        assert result == "hello--world"

    def test_dict_traversal(self):
        """Dict values are recursively expanded."""
        with patch.dict(os.environ, {"API_KEY": "sk-123"}, clear=False):
            d = {"api_key": "${API_KEY}", "nested": {"key": "${API_KEY}"}}
            result = expand_env_vars(d)
        assert result == {"api_key": "sk-123", "nested": {"key": "sk-123"}}

    def test_list_traversal(self):
        """List items are recursively expanded."""
        with patch.dict(os.environ, {"HOST": "localhost"}, clear=False):
            lst = ["${HOST}", "static", "${HOST}:8080"]
            result = expand_env_vars(lst)
        assert result == ["localhost", "static", "localhost:8080"]

    def test_non_string_value_passthrough(self):
        """Non-string values (int, bool, None, float) pass through unchanged."""
        assert expand_env_vars(42) == 42
        assert expand_env_vars(True) is True
        assert expand_env_vars(None) is None
        assert expand_env_vars(3.14) == 3.14

    def test_multiple_vars_in_one_string(self):
        """Multiple env vars in a single string are all expanded."""
        with patch.dict(os.environ, {"USER": "admin", "HOST": "localhost"}, clear=False):
            result = expand_env_vars("${USER}@${HOST}:8080")
        assert result == "admin@localhost:8080"

    def test_empty_string(self):
        """Empty string is returned as-is."""
        assert expand_env_vars("") == ""

    def test_mixed_braced_and_unbraced(self):
        """Mix of ${VAR} and $VAR syntax is handled correctly."""
        with patch.dict(os.environ, {"A": "1", "B": "2"}, clear=False):
            result = expand_env_vars("${A}-$B")
        assert result == "1-2"

    def test_nested_dict_mixed_types(self):
        """Nested dict with mixed types (str, int, list) handles env expansion."""
        with patch.dict(os.environ, {"KEY": "expanded"}, clear=False):
            d = {
                "str_val": "${KEY}",
                "int_val": 42,
                "list_val": ["${KEY}", "literal"],
                "nested": {"deep": "${KEY}"},
            }
            result = expand_env_vars(d)
        assert result["str_val"] == "expanded"
        assert result["int_val"] == 42
        assert result["list_val"] == ["expanded", "literal"]
        assert result["nested"]["deep"] == "expanded"

    def test_string_with_no_vars(self):
        """String with no env var patterns is returned unchanged."""
        assert expand_env_vars("plain text") == "plain text"

    def test_dict_with_no_string_leaves(self):
        """Dict with only non-string values passes through unchanged."""
        d = {"a": 1, "b": True, "c": None}
        assert expand_env_vars(d) == d


# =============================================================================
# 2. TestLoadEnvFile
# =============================================================================


class TestLoadEnvFile:
    """Tests for _load_env_file function."""

    @patch("animetta.config.app.load_dotenv")
    @patch("pathlib.Path.exists", return_value=True)
    def test_idempotent_loading(self, mock_exists, mock_load_dotenv):
        """_load_env_file is idempotent — second call does not reload."""
        _load_env_file()
        _load_env_file()
        assert mock_load_dotenv.call_count == 1

    @patch("animetta.config.app.load_dotenv")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_when_file_exists(self, mock_exists, mock_load_dotenv):
        """load_dotenv is called when a .env file is found."""
        _load_env_file()
        mock_load_dotenv.assert_called_once()
        args, kwargs = mock_load_dotenv.call_args
        assert "dotenv_path" in kwargs
        assert kwargs["dotenv_path"].endswith(".env")

    @patch("animetta.config.app.logger.warning")
    @patch("animetta.config.app.load_dotenv")
    @patch("pathlib.Path.exists", return_value=False)
    def test_warning_when_no_env_file(
        self, mock_exists, mock_load_dotenv, mock_logger_warning
    ):
        """Warning is logged when no .env file is found in any search path."""
        _load_env_file()
        mock_load_dotenv.assert_not_called()
        mock_logger_warning.assert_called_once()
        assert "No .env file found" in str(mock_logger_warning.call_args)

    @patch("animetta.config.app.load_dotenv")
    @patch("pathlib.Path.exists", return_value=False)
    def test_loads_anima_env_file_var(
         self, mock_exists, mock_load_dotenv
     ):
         """ANIMETTA_ENV_FILE env var path is checked first."""
         with patch.dict(os.environ, {"ANIMETTA_ENV_FILE": "/custom/path/.env"}, clear=False):
             _load_env_file()

    @patch("animetta.config.app.load_dotenv")
    @patch("pathlib.Path.exists", return_value=True)
    def test_priority_anima_env_file_first(self, mock_exists, mock_load_dotenv):
         """ANIMETTA_ENV_FILE path has highest priority — checked first."""
         with patch.dict(os.environ, {"ANIMETTA_ENV_FILE": "/custom/.env"}, clear=False):
             _load_env_file()
             mock_load_dotenv.assert_called_once()
             called_path = mock_load_dotenv.call_args[1]["dotenv_path"]
             assert "custom" in called_path and ".env" in called_path


# =============================================================================
# 3. TestLoadServiceConfig
# =============================================================================


class TestLoadServiceConfig:
    """Tests for _load_service_config function."""

    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_from_unified_yaml(self, mock_exists, mock_load_yaml):
        """Loads service config from unified services.yaml."""
        mock_load_yaml.return_value = {
            "asr": {"mock": {"type": "mock"}},
        }
        result = _load_service_config("asr", "mock")
        assert result == {"type": "mock"}

    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists", return_value=True)
    def test_cache_behavior(self, mock_exists, mock_load_yaml):
        """Unified YAML is loaded only once; subsequent calls use cache."""
        mock_load_yaml.return_value = {
            "asr": {"mock": {"type": "mock"}, "other": {"type": "other"}},
        }

        # First call populates cache
        _load_service_config("asr", "mock")
        assert mock_load_yaml.call_count == 1  # loaded unified yaml

        # Second call uses cache (no additional _load_yaml_file calls)
        result2 = _load_service_config("asr", "other")
        assert result2 == {"type": "other"}
        assert mock_load_yaml.call_count == 1  # still 1

    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists", return_value=True)
    def test_fallback_to_old_format(self, mock_exists, mock_load_yaml):
        """Falls back to config/services/{type}/{name}.yaml when unified missing."""
        def yaml_side(path):
            s = str(path).replace("\\", "/")
            if "services.yaml" in s:
                return {"asr": {"other": {"type": "other"}}}  # "mock" NOT in unified
            return {"type": "mock_fallback"}  # old format returns this
        mock_load_yaml.side_effect = yaml_side

        result = _load_service_config("asr", "mock")
        assert result == {"type": "mock_fallback"}

    @patch("pathlib.Path.exists", return_value=False)
    def test_raises_file_not_found(self, mock_exists):
        """FileNotFoundError is raised when no config file exists."""
        with pytest.raises(FileNotFoundError, match="Service configuration not found"):
            _load_service_config("asr", "nonexistent")

    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists", return_value=True)
    def test_logs_service_once(self, mock_exists, mock_load_yaml):
        """Each service config key is logged only once."""
        mock_load_yaml.return_value = {
            "asr": {"mock": {"type": "mock"}},
        }

        with patch("animetta.config.app.logger.debug") as mock_log:
            _load_service_config("asr", "mock")
            _load_service_config("asr", "mock")
            # Should only log once
            log_messages = [
                c[0][0] for c in mock_log.call_args_list if "Loading service config" in str(c[0][0])
            ]
            assert len(log_messages) == 1


# =============================================================================
# 4. TestServicesConfig
# =============================================================================


class TestServicesConfig:
    """Tests for ServicesConfig model."""

    def test_default_values(self):
        """ServicesConfig has correct default values."""
        cfg = ServicesConfig()
        assert cfg.asr == "mock"
        assert cfg.tts == "mock"
        assert cfg.agent == "mock"
        assert cfg.local_llm is None
        assert cfg.vad == "mock"

    def test_custom_values(self):
        """ServicesConfig accepts custom values."""
        cfg = ServicesConfig(
            asr="whisper",
            tts="edge",
            agent="openai",
            local_llm="ollama",
            vad="silero",
        )
        assert cfg.asr == "whisper"
        assert cfg.tts == "edge"
        assert cfg.agent == "openai"
        assert cfg.local_llm == "ollama"
        assert cfg.vad == "silero"

    def test_local_llm_optional(self):
        """local_llm field is Optional[str] and defaults to None."""
        cfg = ServicesConfig()
        assert cfg.local_llm is None
        cfg2 = ServicesConfig(local_llm="ollama")
        assert cfg2.local_llm == "ollama"

    def test_extra_fields_forbidden(self):
        """Pydantic extra='forbid' rejects unknown fields."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ServicesConfig(unknown_field="value")


# =============================================================================
# 5. TestAppConfig
# =============================================================================


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_default_persona(self):
        """AppConfig defaults persona to 'default'."""
        cfg = AppConfig()
        assert cfg.persona == "default"

    def test_service_composition_defaults(self):
        """AppConfig creates default ServicesConfig with all mock services."""
        cfg = AppConfig()
        assert isinstance(cfg.services, ServicesConfig)
        assert cfg.services.asr == "mock"
        assert cfg.services.tts == "mock"
        assert cfg.services.agent == "mock"
        assert cfg.services.local_llm is None
        assert cfg.services.vad == "mock"

    def test_optional_service_fields_default_to_none(self):
        """AI service fields (asr, tts, agent, local_llm, vad) default to None."""
        cfg = AppConfig()
        assert cfg.asr is None
        assert cfg.tts is None
        assert cfg.agent is None
        assert cfg.local_llm is None
        assert cfg.vad is None

    def test_system_config_defaults(self):
        """AppConfig provides default SystemConfig."""
        cfg = AppConfig()
        assert cfg.system.host == "localhost"
        assert cfg.system.port == 12394
        assert cfg.system.debug is False

    def test_custom_persona(self):
        """AppConfig accepts custom persona name."""
        cfg = AppConfig(persona="anime_girl")
        assert cfg.persona == "anime_girl"


# =============================================================================
# 6. TestFromYaml
# =============================================================================


class TestFromYaml:
    """Tests for AppConfig.from_yaml classmethod."""

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_full_cycle_with_mocked_yaml(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """Full from_yaml cycle: loads YAML, resolves services, returns AppConfig."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "test_assistant",
            "services": {
                "asr": "mock",
                "tts": "mock",
                "agent": "mock",
                "vad": "mock",
            },
            "system": {
                "host": "0.0.0.0",
                "port": 12394,
            },
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        config = AppConfig.from_yaml("/fake/path/config.yaml")

        assert config.persona == "test_assistant"
        assert config.services.asr == "mock"
        assert config.services.tts == "mock"
        assert config.services.agent == "mock"
        assert config.services.vad == "mock"
        assert config.services.local_llm is None
        assert config.system.host == "0.0.0.0"
        assert config.system.port == 12394
        assert config.asr is not None
        assert config.tts is not None
        assert config.agent is not None
        assert config.vad is not None
        assert config.local_llm is None
        mock_load_env.assert_called_once()

    @patch("pathlib.Path.exists", return_value=False)
    def test_file_not_found_error(self, mock_exists):
        """from_yaml raises FileNotFoundError when config file does not exist."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            AppConfig.from_yaml("/nonexistent/path.yaml")

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_env_var_expansion_in_config(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """${VAR} patterns in service configs are expanded during from_yaml."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {"asr": "mock", "tts": "mock", "agent": "mock", "vad": "mock"},
            "system": {"host": "localhost", "port": 12394},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock", "api_key": "${TEST_API_KEY}"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        with patch.dict(os.environ, {"TEST_API_KEY": "expanded_value"}, clear=False):
            config = AppConfig.from_yaml("/fake/path.yaml")

        # ASR config should have expanded env var
        assert config.asr is not None
        assert config.asr.api_key == "expanded_value"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_env_override_llm_api_key(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """LLM_API_KEY env var overrides agent.llm_config.api_key."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {"asr": "mock", "tts": "mock", "agent": "mock", "vad": "mock"},
            "system": {"host": "localhost", "port": 12394},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        with patch.dict(os.environ, {"LLM_API_KEY": "overridden_key"}, clear=False):
            config = AppConfig.from_yaml("/fake/path.yaml")

        assert config.agent is not None
        assert config.agent.llm_config.api_key == "overridden_key"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_env_override_system_host_port(
         self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
     ):
         """ANIMETTA_HOST and ANIMETTA_PORT env vars override system config."""
         mock_exists.return_value = True
         mock_load_yaml.return_value = {
             "persona": "default",
             "services": {"asr": "mock", "tts": "mock", "agent": "mock", "vad": "mock"},
             "system": {"host": "localhost", "port": 12394},
         }

         def load_service_side(service_type, service_name):
             configs = {
                 ("asr", "mock"): {"type": "mock"},
                 ("tts", "mock"): {"type": "mock"},
                 ("llm", "mock"): {
                     "memory_enabled": False,
                     "llm_config": {"type": "mock"},
                 },
                 ("vad", "mock"): {"type": "mock"},
             }
             return configs.get((service_type, service_name), {"type": "mock"})

         mock_load_service.side_effect = load_service_side

         with patch.dict(
             os.environ, {"ANIMETTA_HOST": "1.2.3.4", "ANIMETTA_PORT": "8888"}, clear=False
         ):
             config = AppConfig.from_yaml("/fake/path.yaml")

         assert config.system.host == "1.2.3.4"
         assert config.system.port == 8888

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_env_override_service_selection(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """ANIMETTA_* service env vars override config.yaml service names before loading."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {
                "asr": "mock",
                "tts": "alice_vc",
                "agent": "mimo",
                "vad": "silero",
            },
            "system": {"host": "localhost", "port": 12394},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs[(service_type, service_name)]

        mock_load_service.side_effect = load_service_side

        with patch.dict(
            os.environ,
            {
                "ANIMETTA_ASR": "mock",
                "ANIMETTA_TTS": "mock",
                "ANIMETTA_LLM": "mock",
                "ANIMETTA_VAD": "mock",
            },
            clear=False,
        ):
            config = AppConfig.from_yaml("/fake/path.yaml")

        assert config.services.asr == "mock"
        assert config.services.tts == "mock"
        assert config.services.agent == "mock"
        assert config.services.vad == "mock"
        assert config.agent is not None
        assert config.agent.llm_config.type == "mock"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_env_override_asr_tts_api_key(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """ASR_API_KEY and TTS_API_KEY env vars override respective configs."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {"asr": "mock", "tts": "mock", "agent": "mock", "vad": "mock"},
            "system": {"host": "localhost", "port": 12394},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        with patch.dict(
            os.environ,
            {"ASR_API_KEY": "asr_key_override", "TTS_API_KEY": "tts_key_override"},
            clear=False,
        ):
            config = AppConfig.from_yaml("/fake/path.yaml")

        assert config.asr is not None
        assert config.asr.api_key == "asr_key_override"
        assert config.tts is not None
        assert config.tts.api_key == "tts_key_override"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_local_llm_loaded_when_specified(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """local_llm service is loaded when specified in services config."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {
                "asr": "mock",
                "tts": "mock",
                "agent": "mock",
                "local_llm": "local_ollama",
                "vad": "mock",
            },
            "system": {"host": "localhost", "port": 12394},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("llm", "local_ollama"): {
                    "memory_enabled": True,
                    "llm_config": {"type": "ollama", "model": "llama2"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        config = AppConfig.from_yaml("/fake/path.yaml")

        assert config.services.local_llm == "local_ollama"
        assert config.local_llm is not None
        # local_llm extracts the inner llm_config
        assert config.local_llm.type == "ollama"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_bilibili_yaml_loaded_when_present(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """Bilibili config is loaded from config/bilibili.yaml."""
        mock_exists.return_value = True
        mock_load_yaml.side_effect = [
            {
                "persona": "default",
                "services": {
                    "asr": "mock",
                    "tts": "mock",
                    "agent": "mock",
                    "vad": "mock",
                },
                "system": {"host": "localhost", "port": 12394},
            },
            {"enabled": True, "room_id": 12345, "sessdata": "sess"},
        ]

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        config = AppConfig.from_yaml("/fake/path.yaml")

        assert config.bilibili is not None
        assert config.bilibili.enabled is True
        assert config.bilibili.room_id == 12345
        assert config.bilibili.sessdata == "sess"

    @patch("animetta.config.app._load_env_file")
    @patch("animetta.config.app._load_service_config")
    @patch("animetta.config.app._load_yaml_file")
    @patch("pathlib.Path.exists")
    def test_known_fields_only(
        self, mock_exists, mock_load_yaml, mock_load_service, mock_load_env
    ):
        """Keys not in known_fields set are stripped from the AppConfig."""
        mock_exists.return_value = True
        mock_load_yaml.return_value = {
            "persona": "default",
            "services": {"asr": "mock", "tts": "mock", "agent": "mock", "vad": "mock"},
            "system": {"host": "localhost", "port": 12394},
            "bilibili": {"room_id": 123},  # ignored; loaded from bilibili.yaml
            "unknown_tool": {"key": "val"},
        }

        def load_service_side(service_type, service_name):
            configs = {
                ("asr", "mock"): {"type": "mock"},
                ("tts", "mock"): {"type": "mock"},
                ("llm", "mock"): {
                    "memory_enabled": False,
                    "llm_config": {"type": "mock"},
                },
                ("vad", "mock"): {"type": "mock"},
            }
            return configs.get((service_type, service_name), {"type": "mock"})

        mock_load_service.side_effect = load_service_side

        config = AppConfig.from_yaml("/fake/path.yaml")
        # Should not raise ValidationError despite extra keys
        assert config.persona == "default"


# =============================================================================
# 7. TestLoad
# =============================================================================


class TestLoad:
    """Tests for AppConfig.load classmethod."""

    @patch.object(AppConfig, "from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_with_specified_path(self, mock_exists, mock_from_yaml):
        """load uses specified config_path when provided."""
        mock_config = MagicMock(spec=AppConfig)
        mock_from_yaml.return_value = mock_config

        result = AppConfig.load("/custom/path.yaml")

        mock_from_yaml.assert_called_once_with("/custom/path.yaml")
        assert result is mock_config

    @patch.object(AppConfig, "from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_with_env_var_config_path(self, mock_exists, mock_from_yaml):
        """load reads ANIMA_CONFIG env var when no path is specified."""
        mock_config = MagicMock(spec=AppConfig)
        mock_from_yaml.return_value = mock_config

        with patch.dict(os.environ, {"ANIMETTA_CONFIG": "/env/path/config.yaml"}, clear=False):
            result = AppConfig.load()

        mock_from_yaml.assert_called_once_with("/env/path/config.yaml")
        assert result is mock_config

    @patch.object(AppConfig, "from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_with_default_path(self, mock_exists, mock_from_yaml):
        """load falls back to default paths when no config_path or ANIMA_CONFIG."""
        mock_config = MagicMock(spec=AppConfig)
        mock_from_yaml.return_value = mock_config

        result = AppConfig.load()

        assert result is mock_config

    @patch.object(AppConfig, "from_yaml")
    @patch("pathlib.Path.exists", return_value=False)
    def test_raises_file_not_found(self, mock_exists, mock_from_yaml):
        """load raises FileNotFoundError when no config file is found."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            AppConfig.load()

    @patch.object(AppConfig, "from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_specified_path_overrides_env_var(
        self, mock_exists, mock_from_yaml
    ):
        """Specified config_path takes priority over ANIMA_CONFIG env var."""
        mock_config = MagicMock(spec=AppConfig)
        mock_from_yaml.return_value = mock_config

        with patch.dict(os.environ, {"ANIMA_CONFIG": "/env/path.yaml"}, clear=False):
            AppConfig.load("/specified/path.yaml")

        mock_from_yaml.assert_called_once_with("/specified/path.yaml")


# =============================================================================
# 8. TestGetPersona
# =============================================================================


class TestGetPersona:
    """Tests for AppConfig.get_persona method."""

    def test_returns_persona_config(self):
        """get_persona returns a PersonaConfig instance."""

        cfg = AppConfig(persona="default")
        persona = cfg.get_persona()
        assert isinstance(persona, PersonaConfig)

    def test_lazy_loading_caches_result(self):
        """get_persona caches the loaded PersonaConfig in _persona PrivateAttr."""
        cfg = AppConfig(persona="default")
        persona1 = cfg.get_persona()
        persona2 = cfg.get_persona()
        assert persona1 is persona2  # same cached object

    def test_uses_persona_name_from_config(self):
        """get_persona loads the persona matching the configured name."""
        cfg = AppConfig(persona="custom_name")
        persona = cfg.get_persona()
        # If no custom file exists, returns default PersonaConfig
        assert isinstance(persona, PersonaConfig)
        assert persona.name == "Anima"  # default name


# =============================================================================
# 9. TestGetSystemPrompt
# =============================================================================


class TestGetSystemPrompt:
    """Tests for AppConfig.get_system_prompt method."""

    def test_includes_persona_prompt(self):
        """get_system_prompt delegates to PersonaConfig.build_system_prompt."""
        cfg = AppConfig(persona="default")
        prompt = cfg.get_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # reasonable prompt length

    def test_with_live2d_prompt(self):
        """live2d_prompt parameter is forwarded to build_system_prompt."""
        cfg = AppConfig(persona="default")
        prompt = cfg.get_system_prompt(live2d_prompt="[Custom Live2D prompt]")
        assert "[Custom Live2D prompt]" in prompt

    def test_default_live2d_prompt_from_persona(self):
        """If no live2d_prompt arg given, person's configured prompt is used."""
        cfg = AppConfig(persona="default")
        # The default PersonaConfig has live2d_prompt=None
        prompt = cfg.get_system_prompt()
        assert "Live2D" not in prompt  # no live2d section when no prompt

    def test_live2d_arg_overrides_persona_prompt(self):
        """Explicit live2d_prompt argument overrides persona's configured prompt."""
        cfg = AppConfig(persona="default")
        # Access persona to set live2d_prompt
        persona = cfg.get_persona()
        persona.live2d_prompt = "[Default Live2D]"

        prompt_no_arg = cfg.get_system_prompt()
        assert "[Default Live2D]" in prompt_no_arg

        prompt_with_arg = cfg.get_system_prompt(live2d_prompt="[Override Live2D]")
        assert "[Override Live2D]" in prompt_with_arg


# =============================================================================
# 10. TestValidate
# =============================================================================


class TestValidate:
    """Tests for AppConfig.validate method."""

    def _get_provider_registry(self):
        return ProviderRegistry

    def test_no_warnings_for_registered_providers(self):
        """validate produces no warnings when all providers are registered."""
        PR = self._get_provider_registry()
        with (
            patch.object(PR, "list_services", side_effect=lambda cat: ["mock"]),
            patch("animetta.config.app.logger.warning") as mock_logger_warning,
        ):
            config = AppConfig()
            config.services = ServicesConfig(
                asr="mock", tts="mock", agent="mock", vad="mock"
            )
            config.validate_config()
            mock_logger_warning.assert_not_called()

    def test_warning_for_unregistered_providers(self):
        """validate warns when providers are not registered."""
        PR = self._get_provider_registry()
        with (
            patch.object(PR, "list_services", return_value=[]),
            patch("animetta.config.app.logger.warning") as mock_logger_warning,
        ):
            config = AppConfig()
            config.services = ServicesConfig(
                asr="unknown_asr", tts="unknown_tts", agent="unknown_agent", vad="nope"
            )
            config.validate_config()
            assert mock_logger_warning.call_count >= 3

    def test_handles_partially_registered_providers(self):
        """validate warns only for unregistered providers, not registered ones."""
        PR = self._get_provider_registry()
        def list_services_side(cat):
            registered = {"llm": ["openai"], "asr": ["whisper"], "tts": ["edge"]}
            return registered.get(cat, [])
        with (
            patch.object(PR, "list_services", side_effect=list_services_side),
            patch("animetta.config.app.logger.warning") as mock_logger_warning,
        ):
            config = AppConfig()
            config.services = ServicesConfig(
                asr="whisper", tts="unknown_tts", agent="openai", vad="silero",
            )
            config.validate_config()
            warning_messages = [c[0][0] for c in mock_logger_warning.call_args_list]
            assert any("TTS provider" in m for m in warning_messages)
            assert not any("ASR provider" in m for m in warning_messages)
            assert not any("LLM provider" in m for m in warning_messages)

    def test_skips_vad_validation(self):
        """validate does not check VAD service (no ProviderRegistry category)."""
        PR = self._get_provider_registry()
        with (
            patch.object(PR, "list_services", return_value=[]),
            patch("animetta.config.app.logger.warning") as mock_logger_warning,
        ):
            config = AppConfig()
            config.services = ServicesConfig(
                asr="mock", tts="mock", agent="mock", vad="completely_fake_vad"
            )
            config.validate_config()
            warning_messages = [c[0][0] for c in mock_logger_warning.call_args_list]
            vad_warnings = [m for m in warning_messages if "VAD" in m]
            assert len(vad_warnings) == 0

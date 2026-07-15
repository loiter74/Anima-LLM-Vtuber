from __future__ import annotations

"""Tests for observability manager — singleton, config loading, LangSmith/LangFuse init."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from animetta.orchestration.graph.observability import ObservabilityManager, get_observability

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def mock_langfuse_pkg():
    """Add fake langfuse modules to sys.modules so patch() calls resolve.

    The langfuse package is not installed in the test environment, but
    _init_langfuse() does ``from langfuse.langchain import CallbackHandler``
    and ``from langfuse import Langfuse`` at runtime.  This fixture makes
    those imports succeed with mock objects so we can test the happy path.
    """
    mock_langfuse = MagicMock()
    mock_langchain = MagicMock()
    with patch.dict(sys.modules, {"langfuse": mock_langfuse, "langfuse.langchain": mock_langchain}):
        yield


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton _instance before and after each test so tests are isolated."""
    ObservabilityManager._instance = None
    yield
    ObservabilityManager._instance = None


@pytest.fixture(autouse=True)
def _clean_env_langsmith():
    """Remove LangSmith env vars that might interfere with tests."""
    keys = [
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_PROJECT",
        "LANGCHAIN_ENDPOINT",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
    ]
    backup = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in backup.items():
        if v is not None:
            os.environ[k] = v


@pytest.fixture
def mock_yaml_config():
    """Return a default observability YAML config dict."""
    return {
        "langsmith": {
            "enabled": False,
            "project": "anima",
        },
        "langfuse": {
            "enabled": False,
            "host": "https://us.cloud.langfuse.com",
        },
    }


@pytest.fixture
def manager():
    """Fresh ObservabilityManager instance with singleton reset."""
    return ObservabilityManager()


# ── Singleton pattern ───────────────────────────────────────


class TestSingleton:
    """ObservabilityManager enforces a singleton pattern."""

    def test_two_instances_are_same(self):
        """Calling constructor twice returns the same object."""
        m1 = ObservabilityManager()
        m2 = ObservabilityManager()
        assert m1 is m2

    def test_get_observability_returns_singleton(self):
        """get_observability() returns the singleton."""
        m1 = ObservabilityManager()
        m2 = get_observability()
        assert m1 is m2

    def test_initialized_flag_set_once(self):
        """_initialized is False until initialize() is called."""
        m = ObservabilityManager()
        assert not m._initialized
        assert m._langfuse_handler is None
        assert not m._langsmith_enabled
        assert not m._langfuse_enabled


# ── Config loading ──────────────────────────────────────────


class TestConfigLoading:
    """_load_config() handles various file states."""

    def test_load_config_uses_default_path(self, manager):
        """Default config path points to config/observability.yaml."""
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch("animetta.orchestration.graph.observability.yaml.safe_load", return_value={}),
        ):
            config = manager._load_config()
        assert isinstance(config, dict)

    def test_load_config_file_not_found_returns_defaults(self, manager):
        """Missing config file returns disabled defaults."""
        with patch.object(Path, "exists", return_value=False):
            config = manager._load_config("/nonexistent/path.yaml")
        assert config == {"langsmith": {"enabled": False}, "langfuse": {"enabled": False}}

    def test_load_config_yaml_load_error_returns_defaults(self, manager):
        """A yaml parse error falls back to safe defaults."""
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch(
                "animetta.orchestration.graph.observability.yaml.safe_load",
                side_effect=yaml.YAMLError("bad"),
            ),
        ):
            config = manager._load_config("/some/path.yaml")
        assert config == {"langsmith": {"enabled": False}, "langfuse": {"enabled": False}}

    def test_load_config_returns_parsed_content(self, manager, mock_yaml_config):
        """Valid YAML returns the parsed config as-is."""
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch(
                "animetta.orchestration.graph.observability.yaml.safe_load",
                return_value=mock_yaml_config,
            ),
        ):
            config = manager._load_config("/valid/path.yaml")
        assert config["langsmith"]["project"] == "anima"
        assert not config["langfuse"]["enabled"]


# ── LangSmith initialization ────────────────────────────────


class TestLangSmithInit:
    """_init_langsmith() sets environment variables."""

    def test_langsmith_enabled_sets_env_vars(self, manager):
        """When enabled, LANGCHAIN_TRACING_V2 is set to 'true'."""
        manager._config = {
            "langsmith": {"enabled": True, "api_key": "test-key", "project": "test-proj"},
        }
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langsmith()
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "test-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "test-proj"

    def test_langsmith_enabled_with_endpoint(self, manager):
        """Endpoint env var is also set when provided."""
        manager._config = {
            "langsmith": {
                "enabled": True,
                "endpoint": "https://custom.smith.langchain.com",
            },
        }
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langsmith()
            assert os.environ["LANGCHAIN_ENDPOINT"] == "https://custom.smith.langchain.com"

    def test_langsmith_disabled_does_nothing(self, manager):
        """When disabled, no env vars are set."""
        manager._config = {"langsmith": {"enabled": False}}
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langsmith()
            assert "LANGCHAIN_TRACING_V2" not in os.environ
            assert not manager._langsmith_enabled

    def test_langsmith_enabled_sets_flag(self, manager):
        """_langsmith_enabled is True after successful init."""
        manager._config = {"langsmith": {"enabled": True}}
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langsmith()
            assert manager._langsmith_enabled

    def test_langsmith_skips_empty_api_key(self, manager):
        """If no api_key or project in config, only tracing_v2 is set."""
        manager._config = {"langsmith": {"enabled": True}}
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langsmith()
            assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
            assert "LANGCHAIN_API_KEY" not in os.environ
            assert "LANGCHAIN_PROJECT" not in os.environ


# ── LangFuse initialization ─────────────────────────────────


class TestLangFuseInit:
    """_init_langfuse() creates CallbackHandler."""

    def test_langfuse_disabled_does_nothing(self, manager):
        """When disabled, no import or init happens."""
        manager._config = {"langfuse": {"enabled": False}}
        manager._init_langfuse()
        assert not manager._langfuse_enabled
        assert manager._langfuse_handler is None

    def test_langfuse_enabled_missing_import(self, manager):
        """When langfuse is not installed, a warning is logged and init skipped."""
        manager._config = {
            "langfuse": {"enabled": True, "public_key": "pk", "secret_key": "sk"},
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("animetta.orchestration.graph.observability.logger") as mock_logger,
        ):
            # We patch the import to raise ImportError
            import builtins

            original_import = builtins.__import__

            def _mock_import(name, *args, **kwargs):
                if "langfuse" in name:
                    raise ImportError("no langfuse")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", _mock_import):
                manager._init_langfuse()

            assert not manager._langfuse_enabled
            mock_logger.warning.assert_called_once()
            assert "langfuse not installed" in str(mock_logger.warning.call_args)

    def test_langfuse_enabled_sets_env_from_config(self, manager, mock_langfuse_pkg):
        """Config values are written to env for LangFuse SDK to read."""
        manager._config = {
            "langfuse": {
                "enabled": True,
                "public_key": "pk-from-config",
                "secret_key": "sk-from-config",
                "host": "https://custom.langfuse.com",
            },
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("langfuse.langchain.CallbackHandler"),
            patch("langfuse.Langfuse") as mock_client,
        ):
            manager._init_langfuse()

            assert os.environ.get("LANGFUSE_SECRET_KEY") == "sk-from-config"
            assert os.environ.get("LANGFUSE_HOST") == "https://custom.langfuse.com"
            assert manager._langfuse_enabled
            mock_client.assert_called_once_with(
                public_key="pk-from-config",
                secret_key="sk-from-config",
                host="https://custom.langfuse.com",
            )

    def test_langfuse_missing_public_key_skipped(self, manager):
        """Without public_key and secret_key, init is skipped."""
        manager._config = {"langfuse": {"enabled": True}}
        with patch.dict(os.environ, {}, clear=True):
            manager._init_langfuse()

        assert not manager._langfuse_enabled

    def test_langfuse_respects_existing_env_vars(self, manager, mock_langfuse_pkg):
        """Existing env vars take precedence over config values."""
        manager._config = {
            "langfuse": {
                "enabled": True,
                "public_key": "pk-config",
                "secret_key": "sk-config",
                "host": "https://config.langfuse.com",
            },
        }
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-env",
            "LANGFUSE_SECRET_KEY": "sk-env",
            "LANGFUSE_HOST": "https://env.langfuse.com",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch("langfuse.langchain.CallbackHandler"),
            patch("langfuse.Langfuse") as mock_client,
        ):
            manager._init_langfuse()

            # Existing env values should not be overwritten
            assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-env"
            assert os.environ["LANGFUSE_HOST"] == "https://env.langfuse.com"
            mock_client.assert_called_once_with(
                public_key="pk-env",
                secret_key="sk-env",
                host="https://env.langfuse.com",
            )

    def test_langfuse_creation_failure_logged(self, manager, mock_langfuse_pkg):
        """If Langfuse client creation raises, error is logged."""
        manager._config = {
            "langfuse": {
                "enabled": True,
                "public_key": "pk",
                "secret_key": "sk",
            },
        }
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("langfuse.Langfuse", side_effect=Exception("API error")),
            patch("animetta.orchestration.graph.observability.logger") as mock_logger,
        ):
            manager._init_langfuse()

        assert not manager._langfuse_enabled
        mock_logger.error.assert_called_once()
        assert "API error" in str(mock_logger.error.call_args)


# ── Callbacks property ──────────────────────────────────────


class TestCallbacks:
    """callbacks property returns the correct list."""

    def test_callbacks_empty_when_disabled(self, manager):
        """With no LangFuse handler, callbacks is an empty list."""
        assert manager.callbacks == []

    def test_callbacks_contains_handler(self, manager):
        """With LangFuse enabled, callbacks contains the handler."""
        handler = MagicMock()
        manager._langfuse_handler = handler
        assert manager.callbacks == [handler]

    def test_callbacks_immutable_return(self, manager):
        """Returned list should be a new list each time."""
        manager._langfuse_handler = MagicMock()
        c1 = manager.callbacks
        c2 = manager.callbacks
        assert c1 is not c2  # different list objects
        assert c1 == c2


# ── Initialize orchestrator ────────────────────────────────


class TestInitialize:
    """initialize() orchestrates config loading and provider init."""

    def test_initialize_all_disabled(self, manager, mock_yaml_config):
        """With all providers disabled, initialization runs cleanly."""
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch(
                "animetta.orchestration.graph.observability.yaml.safe_load",
                return_value=mock_yaml_config,
            ),
        ):
            manager.initialize("/fake/config/path.yaml")

        assert manager._initialized
        assert not manager._langsmith_enabled
        assert not manager._langfuse_enabled
        assert manager.callbacks == []

    def test_initialize_langsmith(self, manager):
        """Initializing with LangSmith enabled."""
        config = {"langsmith": {"enabled": True, "project": "test"}}
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch("animetta.orchestration.graph.observability.yaml.safe_load", return_value=config),
            patch.dict(os.environ, {}, clear=True),
        ):
            manager.initialize("/fake/path.yaml")
            assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"

        assert manager._langsmith_enabled

    def test_initialize_langfuse(self, manager, mock_langfuse_pkg):
        """Initializing with LangFuse enabled."""
        config = {
            "langfuse": {
                "enabled": True,
                "public_key": "pk",
                "secret_key": "sk",
                "host": "https://test.langfuse.com",
            },
        }
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch("animetta.orchestration.graph.observability.yaml.safe_load", return_value=config),
            patch("langfuse.langchain.CallbackHandler"),
            patch("langfuse.Langfuse"),
            patch.dict(os.environ, {}, clear=True),
        ):
            manager.initialize("/fake/path.yaml")

        assert manager._langfuse_enabled
        assert manager._langfuse_handler is not None
        assert manager.callbacks == [manager._langfuse_handler]

    def test_initialize_idempotent(self, manager):
        """Calling initialize twice only runs once."""
        with (
            patch.object(manager, "_load_config", return_value={}) as mock_load,
            patch.object(manager, "_init_langsmith") as mock_ls,
            patch.object(manager, "_init_langfuse") as mock_lf,
        ):
            manager.initialize("/fake.yaml")
            manager.initialize("/fake.yaml")

        mock_load.assert_called_once()
        mock_ls.assert_called_once()
        mock_lf.assert_called_once()

    def test_initialize_both_providers(self, manager, mock_langfuse_pkg):
        """LangSmith and LangFuse can both be enabled simultaneously."""
        config = {
            "langsmith": {"enabled": True, "api_key": "ls-key"},
            "langfuse": {
                "enabled": True,
                "public_key": "pk",
                "secret_key": "sk",
            },
        }
        with (
            patch.object(Path, "exists", return_value=True),
            patch("animetta.orchestration.graph.observability.open", MagicMock()),
            patch("animetta.orchestration.graph.observability.yaml.safe_load", return_value=config),
            patch("langfuse.langchain.CallbackHandler"),
            patch("langfuse.Langfuse"),
            patch.dict(os.environ, {}, clear=True),
        ):
            manager.initialize("/fake.yaml")

        assert manager._langsmith_enabled
        assert manager._langfuse_enabled
        assert len(manager.callbacks) == 1  # only LangFuse handler


# ── Status ──────────────────────────────────────────────────


class TestStatus:
    """get_status() returns the current state."""

    def test_status_all_disabled(self, manager):
        """Default state shows all disabled."""
        status = manager.get_status()
        assert status == {"langsmith_enabled": False, "langfuse_enabled": False}

    def test_status_after_init(self, manager):
        """Status reflects enabled providers after initialization."""
        manager._langsmith_enabled = True
        manager._langfuse_enabled = True
        assert manager.get_status() == {"langsmith_enabled": True, "langfuse_enabled": True}

    @pytest.mark.parametrize(
        ("ls", "lf"),
        [
            (True, False),
            (False, True),
            (True, True),
            (False, False),
        ],
    )
    def test_status_all_combinations(self, manager, ls, lf):
        """Status correctly reports all enable/disable combinations."""
        manager._langsmith_enabled = ls
        manager._langfuse_enabled = lf
        status = manager.get_status()
        assert status["langsmith_enabled"] is ls
        assert status["langfuse_enabled"] is lf


# ── Properties ──────────────────────────────────────────────


class TestProperties:
    """langsmith_enabled / langfuse_enabled property accessors."""

    def test_langsmith_enabled_property(self, manager):
        manager._langsmith_enabled = True
        assert manager.langsmith_enabled

    def test_langfuse_enabled_property(self, manager):
        manager._langfuse_enabled = True
        assert manager.langfuse_enabled

from __future__ import annotations

from animetta.config.providers.llm import (
    GLMLLMConfig,
    MockLLMConfig,
    OllamaLLMConfig,
    OpenAILLMConfig,
)
from animetta.services.llm import LLMFactory

"""Tests for LLMFactory — provider-based LLM service instantiation.

Covers ``create_from_config`` (discriminated union dispatch) and
``create`` (provider-name + kwargs path) with mocked registries
and fallback behaviour.
"""

from unittest.mock import AsyncMock, MagicMock, patch

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _mock_service():
    """Return a MagicMock that quacks like an LLMInterface."""
    svc = MagicMock()
    svc.chat = AsyncMock(return_value="mock reply")
    svc.chat_stream = AsyncMock()
    svc.set_system_prompt = MagicMock()
    svc.get_history = MagicMock(return_value=[])
    svc.clear_history = MagicMock()
    svc.close = AsyncMock()
    return svc


# ═══════════════════════════════════════════════════════════════════════
# create_from_config
# ═══════════════════════════════════════════════════════════════════════


class TestCreateFromConfig:
    """LLMFactory.create_from_config() — config-object path."""

    # ── Happy path ──────────────────────────────────────────────

    def test_mock_config(self):
        """MockLLMConfig creates a service via ProviderRegistry."""

        mock_svc = _mock_service()

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            return_value=mock_svc,
        ) as mock_create, patch(
            "animetta.services.llm.factory.TracingProxy",
            side_effect=lambda x, **kw: x,
        ):
            config = MockLLMConfig()
            result = LLMFactory.create_from_config(config, system_prompt="Hello")

            # ProviderRegistry was called with the config
            mock_create.assert_called_once_with("llm", config, system_prompt="Hello")
            assert result is mock_svc

    def test_openai_config(self):
        """OpenAILLMConfig creates a service via ProviderRegistry."""

        mock_svc = _mock_service()

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            return_value=mock_svc,
        ) as mock_create, patch(
            "animetta.services.llm.factory.TracingProxy",
            side_effect=lambda x, **kw: x,
        ):
            config = OpenAILLMConfig(api_key="sk-test", model="gpt-4")
            result = LLMFactory.create_from_config(config)

            mock_create.assert_called_once_with("llm", config, system_prompt="")
            assert result is mock_svc

    def test_glm_config(self):
        """GLMLLMConfig creates a service via ProviderRegistry."""

        mock_svc = _mock_service()

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            return_value=mock_svc,
        ) as mock_create, patch(
            "animetta.services.llm.factory.TracingProxy",
            side_effect=lambda x, **kw: x,
        ):
            config = GLMLLMConfig(api_key="glm-key", model="glm-4")
            result = LLMFactory.create_from_config(config, system_prompt="Be helpful")

            mock_create.assert_called_once_with("llm", config, system_prompt="Be helpful")
            assert result is mock_svc

    def test_ollama_config(self):
        """OllamaLLMConfig creates a service via ProviderRegistry."""

        mock_svc = _mock_service()

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            return_value=mock_svc,
        ) as mock_create, patch(
            "animetta.services.llm.factory.TracingProxy",
            side_effect=lambda x, **kw: x,
        ):
            config = OllamaLLMConfig(model="llama3.2")
            result = LLMFactory.create_from_config(config)

            mock_create.assert_called_once_with("llm", config, system_prompt="")
            assert result is mock_svc

    # ── TracingProxy wrapping ───────────────────────────────────

    def test_wraps_in_tracing_proxy(self):
        """The returned service is wrapped in a TracingProxy."""

        mock_svc = _mock_service()

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            return_value=mock_svc,
        ), patch(
            "animetta.services.llm.factory.TracingProxy",
            return_value="proxy-wrapped",
        ) as mock_proxy:
            config = MockLLMConfig()
            result = LLMFactory.create_from_config(config)

            mock_proxy.assert_called_once_with(mock_svc, service_name="llm")
            assert result == "proxy-wrapped"

    # ── Fallback ─────────────────────────────────────────────────

    def test_fallback_to_mock_on_error(self):
        """When ProviderRegistry raises, factory falls back to MockLLM."""

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            side_effect=ValueError("unknown provider"),
        ), patch(
            "animetta.services.llm.mock_llm.MockLLM",
        ) as MockMockLLM:
            mock_instance = _mock_service()
            MockMockLLM.return_value = mock_instance

            config = OpenAILLMConfig(api_key="test")
            result = LLMFactory.create_from_config(config, system_prompt="Hello")

            MockMockLLM.assert_called_once_with(system_prompt="Hello")
            assert result is mock_instance

    def test_fallback_to_mock_on_import_error(self):
        """ImportError during service creation also triggers fallback."""

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            side_effect=ImportError("missing dependency"),
        ), patch(
            "animetta.services.llm.mock_llm.MockLLM",
        ) as MockMockLLM:
            mock_instance = _mock_service()
            MockMockLLM.return_value = mock_instance

            config = MockLLMConfig()
            result = LLMFactory.create_from_config(config)

            MockMockLLM.assert_called_once()
            assert result is mock_instance

    def test_fallback_uses_original_system_prompt(self):
        """Fallback MockLLM receives the same system_prompt."""

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.create_service",
            side_effect=Exception("fail"),
        ), patch(
            "animetta.services.llm.mock_llm.MockLLM",
        ) as MockMockLLM:
            mock_instance = _mock_service()
            MockMockLLM.return_value = mock_instance

            config = MockLLMConfig()
            LLMFactory.create_from_config(config, system_prompt="Custom prompt")

            MockMockLLM.assert_called_once_with(system_prompt="Custom prompt")


# ═══════════════════════════════════════════════════════════════════════
# create (provider-name + kwargs path)
# ═══════════════════════════════════════════════════════════════════════


class TestCreate:
    """LLMFactory.create() — provider-name + kwargs path."""

    def test_mock_provider(self):
        """``create("mock")`` returns a MockLLM instance."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create("mock")
            mock_create.assert_called_once()
            # Verify the config passed is MockLLMConfig
            config_arg = mock_create.call_args[0][0]
            assert isinstance(config_arg, MockLLMConfig)

    def test_openai_provider(self):
        """``create("openai", api_key=..., model=...)`` passes kwargs to config."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create(
                "openai",
                api_key="sk-test",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                temperature=0.5,
                max_tokens=2000,
            )

            config_arg = mock_create.call_args[0][0]
            assert isinstance(config_arg, OpenAILLMConfig)
            assert config_arg.api_key == "sk-test"
            assert config_arg.model == "gpt-4"
            assert config_arg.temperature == 0.5
            assert config_arg.max_tokens == 2000

    def test_glm_provider(self):
        """``create("glm", api_key=...)`` builds a GLMLLMConfig with defaults."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create(
                "glm",
                api_key="glm-key",
                enable_thinking=True,
            )

            config_arg = mock_create.call_args[0][0]
            assert isinstance(config_arg, GLMLLMConfig)
            assert config_arg.api_key == "glm-key"
            assert config_arg.model == "glm-4-flash"  # default
            assert config_arg.enable_thinking is True

    def test_ollama_provider(self):
        """``create("ollama")`` builds an OllamaLLMConfig with defaults."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create(
                "ollama",
                model="llama3.2",
                base_url="http://192.168.1.100:11434",
            )

            config_arg = mock_create.call_args[0][0]
            assert isinstance(config_arg, OllamaLLMConfig)
            assert config_arg.model == "llama3.2"
            assert config_arg.base_url == "http://192.168.1.100:11434"

    def test_system_prompt_propagation(self):
        """``system_prompt`` is forwarded as positional arg to ``create_from_config``."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create("mock", system_prompt="Be polite")

            # create() passes system_prompt as the second positional argument
            args, _ = mock_create.call_args
            assert len(args) >= 2
            assert args[1] == "Be polite"

    def test_unknown_provider_falls_back_to_mock(self):
        """An unrecognised provider name results in a MockLLMConfig."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            LLMFactory.create("nonexistent_provider")

            config_arg = mock_create.call_args[0][0]
            assert isinstance(config_arg, MockLLMConfig)

    def test_unknown_provider_warns(self):
        """An unknown provider triggers a warning log and MockLLM config."""

        with patch(
            "animetta.services.llm.factory.LLMFactory.create_from_config",
        ) as mock_create:
            mock_create.return_value = _mock_service()

            with patch(
                "animetta.services.llm.factory.logger.warning"
            ) as mock_warn:
                LLMFactory.create("unknown_xyz")

                mock_warn.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# get_available_configs
# ═══════════════════════════════════════════════════════════════════════


class TestGetAvailableConfigs:
    """LLMFactory.get_available_configs() — registry listing."""

    def test_returns_list(self):

        with patch(
            "animetta.services.llm.factory.ProviderRegistry.list_services",
            return_value=["mock", "openai", "glm", "ollama"],
        ):
            providers = LLMFactory.get_available_configs()
            assert isinstance(providers, list)
            assert len(providers) >= 1

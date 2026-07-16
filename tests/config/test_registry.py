from __future__ import annotations

from animetta.config.core.registry import ProviderRegistry

"""Tests for ProviderRegistry (config/core/registry.py)"""

import sys
import types
from pathlib import Path
from typing import Literal

import pytest

from animetta.config.core.base import ProviderConfig

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def registry():
    """Fixture providing a clean ProviderRegistry state for each test.

    Saves and restores the original class-level dicts so tests never leak state.
    Seeds known service categories so tests can register services directly.
    """
    saved = {
        "_configs": ProviderRegistry._configs,
        "_services": ProviderRegistry._services,
    }
    ProviderRegistry._configs = {}
    ProviderRegistry._services = {
        "llm": {},
        "asr": {},
        "tts": {},
        "vad": {},
        "separation": {},
        "vc": {},
    }
    yield ProviderRegistry
    ProviderRegistry._configs = saved["_configs"]
    ProviderRegistry._services = saved["_services"]


# ═══════════════════════════════════════════════════════════════
# Mock classes for testing
# ═══════════════════════════════════════════════════════════════


class MockOpenAIConfig(ProviderConfig):
    """Mock OpenAI LLM config for testing"""

    type: Literal["openai"] = "openai"
    api_key: str = "test_key"


class MockGLMConfig(ProviderConfig):
    """Mock GLM config for testing"""

    type: Literal["glm"] = "glm"
    api_key: str = "test_key"


class MockWhisperConfig(ProviderConfig):
    """Mock Whisper ASR config for testing"""

    type: Literal["whisper"] = "whisper"
    model: str = "base"


class MockServiceWithFromConfig:
    """Mock service class that has from_config classmethod"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @classmethod
    def from_config(cls, config: ProviderConfig, **extra_kwargs) -> MockServiceWithFromConfig:
        return cls(config=config, **extra_kwargs)


class MockServiceNoFromConfig:
    """Mock service class that is MISSING from_config"""

    pass


# ═══════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════


class TestRegisterConfig:
    """Tests for ProviderRegistry.register_config"""

    def test_register_config_stores_with_category_and_type(self, registry):
        """register_config decorator stores class in _configs dict with correct category/type"""

        @registry.register_config("llm", "openai")
        class TestConfig(ProviderConfig):
            type: Literal["test"] = "test"

        assert "openai" in registry._configs["llm"]
        assert registry._configs["llm"]["openai"] is TestConfig

    def test_register_config_multiple_categories(self, registry):
        """register_config works across different categories"""

        @registry.register_config("llm", "openai")
        class LLMConfig(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_config("asr", "whisper")
        class ASRConfig(ProviderConfig):
            type: Literal["whisper"] = "whisper"

        assert registry._configs["llm"]["openai"] is LLMConfig
        assert registry._configs["asr"]["whisper"] is ASRConfig
        # Verify isolation across categories
        assert "whisper" not in registry._configs["llm"]

    def test_register_config_returns_the_class(self, registry):
        """register_config decorator returns the same class (does not wrap it)"""

        class MyConfig(ProviderConfig):
            type: Literal["my"] = "my"

        result = registry.register_config("llm", "my")(MyConfig)
        assert result is MyConfig


class TestRegisterAlias:
    """Tests for ProviderRegistry.register_config (primary API)"""

    def test_register_config_stores_in_configs(self, registry):
        """register_config() stores class in _configs dict"""

        @registry.register_config("llm", "test_model")
        class TestConfig(ProviderConfig):
            type: Literal["test_model"] = "test_model"

        assert registry._configs["llm"]["test_model"] is TestConfig

    def test_register_config_multiple_calls_same_dict(self, registry):
        """Multiple register_config calls write to the same dict"""

        @registry.register_config("llm", "from_a")
        class A(ProviderConfig):
            type: Literal["a"] = "a"

        @registry.register_config("llm", "from_b")
        class B(ProviderConfig):
            type: Literal["b"] = "b"

        assert "from_a" in registry._configs["llm"]
        assert "from_b" in registry._configs["llm"]


class TestRegisterService:
    """Tests for ProviderRegistry.register_service"""

    def test_register_service_stores_class(self, registry):
        """register_service stores class in _services dict"""

        @registry.register_service("llm", "openai")
        class OpenAIService:
            pass

        assert "openai" in registry._services["llm"]
        assert registry._services["llm"]["openai"] is OpenAIService

    def test_register_service_multiple_categories(self, registry):
        """register_service works across different categories"""

        @registry.register_service("llm", "openai")
        class LLMService:
            pass

        @registry.register_service("tts", "edge")
        class TTSService:
            pass

        assert registry._services["llm"]["openai"] is LLMService
        assert registry._services["tts"]["edge"] is TTSService

    def test_register_service_returns_the_class(self, registry):
        """register_service decorator returns the same class"""

        class MyService:
            pass

        result = registry.register_service("llm", "my")(MyService)
        assert result is MyService


class TestGetServiceClass:
    """Tests for ProviderRegistry.get_service_class"""

    def test_returns_correct_class(self, registry):
        """get_service_class returns the registered service class"""

        @registry.register_service("llm", "openai")
        class OpenAIService:
            pass

        result = registry.get_service_class("llm", "openai")
        assert result is OpenAIService

    def test_returns_none_for_unknown_category(self, registry):
        """get_service_class returns None for non-existent category"""
        result = registry.get_service_class("nonexistent", "anything")
        assert result is None

    def test_returns_none_for_unknown_type(self, registry):
        """get_service_class returns None for non-existent provider type"""

        @registry.register_service("llm", "openai")
        class OpenAIService:
            pass

        result = registry.get_service_class("llm", "unknown")
        assert result is None


class TestCreateService:
    """Tests for ProviderRegistry.create_service"""

    def test_calls_from_config_with_kwargs(self, registry):
        """create_service calls from_config with config and extra kwargs"""
        registry._services["llm"]["openai"] = MockServiceWithFromConfig
        config = MockOpenAIConfig(api_key="test123")

        instance = registry.create_service("llm", config, extra_param="hello")

        assert isinstance(instance, MockServiceWithFromConfig)
        assert instance.kwargs["config"] is config
        assert instance.kwargs["extra_param"] == "hello"

    def test_raises_value_error_for_unknown_type(self, registry):
        """create_service raises ValueError when no service registered for type"""
        config = MockOpenAIConfig(api_key="test")
        with pytest.raises(ValueError, match="Service implementation not found"):
            registry.create_service("llm", config)

    def test_raises_value_error_when_missing_from_config(self, registry):
        """create_service raises ValueError when service class lacks from_config"""
        registry._services["llm"]["openai"] = MockServiceNoFromConfig
        config = MockOpenAIConfig(api_key="test")

        with pytest.raises(ValueError, match="missing the from_config class method"):
            registry.create_service("llm", config)

    def test_raises_value_error_for_unknown_category(self, registry):
        """create_service raises ValueError for unknown category"""
        config = MockOpenAIConfig(api_key="test")
        with pytest.raises(ValueError):
            registry.create_service("nonexistent", config)


class TestListServices:
    """Tests for ProviderRegistry.list_services"""

    def test_list_services_returns_registered_names(self, registry):
        """list_services returns names of all registered services"""

        @registry.register_service("llm", "svc_a")
        class ServiceA:
            pass

        @registry.register_service("llm", "svc_b")
        class ServiceB:
            pass

        names = registry.list_services("llm")
        assert sorted(names) == ["svc_a", "svc_b"]

    def test_list_services_empty(self, registry):
        """list_services returns empty list when no services registered"""
        assert registry.list_services("llm") == []

    def test_list_services_unknown_category(self, registry):
        """list_services returns empty list for unknown category"""
        assert registry.list_services("unknown_cat") == []


class TestGet:
    """Tests for ProviderRegistry.get_config"""

    def test_returns_config_class(self, registry):
        """get_config returns the registered config class"""

        @registry.register_config("llm", "openai")
        class ConfigClass(ProviderConfig):
            type: Literal["openai"] = "openai"

        result = registry.get_config("llm", "openai")
        assert result is ConfigClass

    def test_returns_none_for_unknown(self, registry):
        """get_config returns None when provider not found"""
        result = registry.get_config("llm", "nonexistent")
        assert result is None

    def test_reads_from_configs(self, registry):
        """get_config reads from _configs dict"""

        @registry.register_config("tts", "edge")
        class EdgeConfig(ProviderConfig):
            type: Literal["edge"] = "edge"

        result = registry.get_config("tts", "edge")
        assert result is EdgeConfig


class TestListProviders:
    """Tests for ProviderRegistry.list_configs"""

    def test_list_configs_returns_names(self, registry):
        """list_configs returns registered config names"""

        @registry.register_config("llm", "p1")
        class P1Config(ProviderConfig):
            type: Literal["p1"] = "p1"

        @registry.register_config("llm", "p2")
        class P2Config(ProviderConfig):
            type: Literal["p2"] = "p2"

        names = registry.list_configs("llm")
        assert sorted(names) == ["p1", "p2"]

    def test_list_configs_empty(self, registry):
        """list_configs returns empty list for empty category"""
        assert registry.list_configs("vad") == []


class TestGetAllProviders:
    """Tests for ProviderRegistry.get_all_configs"""

    def test_get_all_configs_returns_copy(self, registry):
        """get_all_configs returns all providers as a nested dict"""

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_config("llm", "glm")
        class GLMCfg(ProviderConfig):
            type: Literal["glm"] = "glm"

        @registry.register_config("asr", "whisper")
        class WhisperCfg(ProviderConfig):
            type: Literal["whisper"] = "whisper"

        all_configs = registry.get_all_configs()

        assert "llm" in all_configs
        assert "asr" in all_configs
        assert all_configs["llm"]["openai"] is OpenAICfg
        assert all_configs["asr"]["whisper"] is WhisperCfg

    def test_get_all_configs_is_top_level_copy(self, registry):
        """get_all_configs returns a top-level copy (inner dicts are shared references)"""

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        all_configs = registry.get_all_configs()

        # Modifying the top-level dict should not affect the original
        all_configs["new_cat"] = {}
        assert "new_cat" not in registry._configs

    def test_get_all_configs_empty(self, registry):
        """get_all_configs returns empty dict when nothing registered"""
        all_configs = registry.get_all_configs()
        assert all_configs == {}


class TestCreateUnionType:
    """Tests for ProviderRegistry.create_union_type"""

    def test_creates_annotated_union(self, registry):
        """create_union_type returns Annotated[Union[...], Field(discriminator='type')]"""
        import typing

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_config("llm", "glm")
        class GLMCfg(ProviderConfig):
            type: Literal["glm"] = "glm"

        result = registry.create_union_type("llm")

        # Verify it's an Annotated type
        origin = typing.get_origin(result)
        assert origin is typing.Annotated

        # The first arg should be a Union containing our config classes.
        # In Python 3.13+, `X | Y` produces types.UnionType instead of typing.Union.
        args = typing.get_args(result)
        union_type = args[0]
        assert typing.get_origin(union_type) in (typing.Union, types.UnionType)

        union_args = typing.get_args(union_type)
        assert OpenAICfg in union_args
        assert GLMCfg in union_args

    def test_raises_value_error_when_no_providers(self, registry):
        """create_union_type raises ValueError when no providers registered"""
        with pytest.raises(ValueError, match="No registered"):
            registry.create_union_type("llm")

    def test_creates_single_element_union(self, registry):
        """create_union_type works with a single provider"""
        import typing

        @registry.register_config("tts", "edge")
        class EdgeCfg(ProviderConfig):
            type: Literal["edge"] = "edge"

        result = registry.create_union_type("tts")

        # Union[X] is unwrapped to X at runtime, so check origin differently
        origin = typing.get_origin(result)
        assert origin is typing.Annotated

        # First arg - in single-provider case it's the class itself (Union unwrapped)
        args = typing.get_args(result)
        assert args[0] is EdgeCfg


class TestClear:
    """Tests for ProviderRegistry.clear"""

    def test_clear_specific_category(self, registry):
        """clear(category) clears only the specified category"""

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_config("asr", "whisper")
        class WhisperCfg(ProviderConfig):
            type: Literal["whisper"] = "whisper"

        registry.clear("llm")

        assert registry._configs.get("llm") is None
        assert "whisper" in registry._configs["asr"]

    def test_clear_all(self, registry):
        """clear() with no args clears all categories"""

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_config("asr", "whisper")
        class WhisperCfg(ProviderConfig):
            type: Literal["whisper"] = "whisper"

        @registry.register_config("tts", "edge")
        class EdgeCfg(ProviderConfig):
            type: Literal["edge"] = "edge"

        @registry.register_config("vad", "silero")
        class SileroCfg(ProviderConfig):
            type: Literal["silero"] = "silero"

        registry.clear()

        assert registry._configs == {}

    def test_clear_does_not_affect_services(self, registry):
        """clear should only affect provider configs, not service registrations"""

        @registry.register_config("llm", "openai")
        class OpenAICfg(ProviderConfig):
            type: Literal["openai"] = "openai"

        @registry.register_service("llm", "openai")
        class OpenAIService:
            pass

        registry.clear()

        # Providers cleared
        assert registry._configs == {}
        # Services untouched
        assert registry._services["llm"]["openai"] is OpenAIService

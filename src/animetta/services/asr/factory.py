"""
ASR Factory - creates ASR instances based on configuration.
"""

from __future__ import annotations

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.asr import (
    FasterWhisperASRConfig,
    FunASRConfig,
    GLMASRConfig,
    MockASRConfig,
    OpenAIASRConfig,
)
from animetta.tracing.proxy import TracingProxy

from .interface import ASRInterface
from .mock_asr import MockASR


class ASRFactory:
    """ASR service factory class"""

    # Maps provider name → config class instantiation (kwargs-based)
    _CONFIG_MAP = {}

    @staticmethod
    def create(provider: str, **kwargs) -> ASRInterface:
        """
        Creates ASR instance by provider via ProviderRegistry.

        Args:
            provider: Provider name (e.g. "faster_whisper", "glm", "funasr", "mock")
            **kwargs: Parameters passed to build the config object

        Returns:
            ASRInterface: ASR instance

        Falls back to MockASR on failure.
        """
        # Build a config object matching the provider type
        config = ASRFactory._build_config(provider, kwargs)
        if config is None:
            logger.warning(f"Unknown ASR provider: {provider}, using Mock implementation")
            return MockASR()

        try:
            svc = ProviderRegistry.create_service("asr", config)
            return TracingProxy(svc, service_name="asr")
        except Exception as e:
            logger.warning(f"Failed to create ASR ({provider}): {e}, falling back to Mock")
            return MockASR()

    @staticmethod
    def _build_config(provider: str, kwargs: dict):
        """Build a config Pydantic object from kwargs, or None if unknown."""
        try:
            if provider == "openai":
                return OpenAIASRConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "whisper-1"),
                    language=kwargs.get("language", "zh"),
                    base_url=kwargs.get("base_url"),
                )
            elif provider == "funasr":
                return FunASRConfig(
                    model=kwargs.get("model", "paraformer-zh"),
                    language=kwargs.get("language", "zh"),
                    device=kwargs.get("device", "cuda"),
                    ncpu=kwargs.get("ncpu", 4),
                    vad_model=kwargs.get("vad_model", "fsmn-vad"),
                    punc_model=kwargs.get("punc_model", "ct-punc"),
                    spk_model=kwargs.get("spk_model"),
                    hotword=kwargs.get("hotword"),
                    model_hub=kwargs.get("model_hub", "ms"),
                    disable_update=kwargs.get("disable_update", True),
                )
            elif provider == "glm":
                return GLMASRConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "glm-asr"),
                    stream=kwargs.get("stream", False),
                )
            elif provider == "faster_whisper":
                return FasterWhisperASRConfig(
                    model=kwargs.get("model", "distil-large-v3"),
                    language=kwargs.get("language", "zh"),
                    device=kwargs.get("device", "auto"),
                    compute_type=kwargs.get("compute_type", "default"),
                    download_root=kwargs.get("download_root"),
                    beam_size=kwargs.get("beam_size", 5),
                    vad_filter=kwargs.get("vad_filter", True),
                    vad_parameters=kwargs.get("vad_parameters", {}),
                )
            elif provider == "mock":
                return MockASRConfig()
            else:
                return None
        except ImportError as e:
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get list of all available providers"""
        return list(ProviderRegistry.list_services("asr"))

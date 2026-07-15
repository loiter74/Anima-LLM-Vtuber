"""
ASR Factory - creates ASR instances based on configuration.
"""

from __future__ import annotations

from importlib import import_module

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.asr import (
    FasterWhisperASRConfig,
    FunASRConfig,
    GLMASRConfig,
    MimoASRConfig,
    MockASRConfig,
    OpenAIASRConfig,
)
from animetta.observability.ports import ObservationRecorder
from animetta.observability.service_proxy import instrument_service

from .interface import ASRInterface
from .mock_asr import MockASR

_AVAILABLE_ASR_PROVIDERS = (
    "mock",
    "funasr",
    "glm",
    "mimo",
    "faster_whisper",
)


class ASRFactory:
    """ASR service factory class"""

    # Maps provider name → config class instantiation (kwargs-based)
    _CONFIG_MAP = {}

    @staticmethod
    def create(
        provider: str,
        *,
        strict: bool = False,
        observation_recorder: ObservationRecorder | None = None,
        **kwargs,
    ) -> ASRInterface:
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
            if strict:
                raise ValueError(f"Unknown ASR provider: {provider}")
            logger.warning(f"Unknown ASR provider: {provider}, using Mock implementation")
            return instrument_service(
                MockASR(), observation_recorder, "asr", provider="mock", model="mock"
            )

        try:
            normalized_provider = provider.replace("_", "-")
            module_name = {
                "mock": ".mock_asr",
                "openai": ".openai_asr",
                "funasr": ".funasr_asr",
                "glm": ".glm_asr",
                "mimo": ".mimo_asr",
                "mimo-asr": ".mimo_asr",
                "faster-whisper": ".faster_whisper_asr",
            }.get(normalized_provider)
            if module_name is not None:
                try:
                    import_module(module_name, __package__)
                except ImportError as exc:
                    if strict:
                        raise
                    logger.warning(
                        "ASR provider import unavailable: "
                        f"type={provider}, error={type(exc).__name__}"
                    )
            svc = ProviderRegistry.create_service("asr", config)
            if strict and provider != "mock" and isinstance(svc, MockASR):
                raise RuntimeError(
                    "Strict ASR provider creation returned MockASR for a non-mock config"
                )
            return instrument_service(
                svc,
                observation_recorder,
                "asr",
                provider=provider,
                model=getattr(config, "model", None),
            )
        except Exception as e:
            if strict:
                raise
            logger.warning(
                "ASR provider failed to initialize; falling back to MockASR: "
                f"type={provider}, error={type(e).__name__}"
            )
            return instrument_service(
                MockASR(), observation_recorder, "asr", provider="mock", model="mock"
            )

    @staticmethod
    def _build_config(provider: str, kwargs: dict):
        """Build a config Pydantic object from kwargs, or None if unknown."""
        normalized_provider = provider.replace("_", "-")
        try:
            if normalized_provider == "openai":
                return OpenAIASRConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "whisper-1"),
                    language=kwargs.get("language", "zh"),
                    base_url=kwargs.get("base_url"),
                )
            elif normalized_provider == "funasr":
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
            elif normalized_provider == "glm":
                return GLMASRConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "glm-asr"),
                    stream=kwargs.get("stream", False),
                )
            elif normalized_provider in {"mimo", "mimo-asr"}:
                return MimoASRConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "mimo-v2.5-asr"),
                    language=kwargs.get("language", "auto"),
                    base_url=kwargs.get("base_url", "https://api.xiaomimimo.com/v1"),
                    sample_rate=kwargs.get("sample_rate", 16000),
                    input_audio_format=kwargs.get("input_audio_format", "pcm_s16le"),
                    timeout=kwargs.get("timeout", 30.0),
                )
            elif normalized_provider == "faster-whisper":
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
            elif normalized_provider == "mock":
                return MockASRConfig()
            else:
                return None
        except ImportError as e:
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get the stable catalog of providers with service implementations."""
        return list(_AVAILABLE_ASR_PROVIDERS)

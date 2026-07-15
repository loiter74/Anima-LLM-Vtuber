from __future__ import annotations

from importlib import import_module

"""
TTS Factory - creates TTS instances based on configuration

Uses ProviderRegistry for automatic service discovery and instantiation.
To add a new TTS provider, simply:
1. Create a config class with @ProviderRegistry.register("tts", "type")
2. Create a service class with @ProviderRegistry.register_service("tts", "type")
   and a from_config() classmethod
"""


from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts import (
    ChatTTSConfig,
    EdgeTTSConfig,
    GLMTTSConfig,
    GPTSoVITSConfig,
    KokoroTTSConfig,
    MimoTTSConfig,
    MockTTSConfig,
    OpenAITTSConfig,
    Qwen3TTSConfig,
    RemoteTTSConfig,
    VibeVoiceTTSConfig,
)
from animetta.observability.ports import ObservationRecorder
from animetta.observability.service_proxy import (
    InstrumentedServiceProxy,
    instrument_service,
)
from animetta.tracing.proxy import TracingProxy

from .interface import TTSInterface
from .mimo_tts import MimoTTS  # noqa: F401 - ensure provider registration
from .mock_tts import MockTTS
from .remote_tts import RemoteTTS  # noqa: F401 - ensure provider registration

_AVAILABLE_TTS_PROVIDERS = (
    "mock",
    "edge",
    "mimo",
    "gpt_sovits",
    "qwen3",
    "remote",
    "glm",
    "chattts",
    "kokoro",
    "vibe_voice",
)


def _unwrap_tracing_proxy(service: object) -> object:
    """Return the concrete service behind any nested tracing proxies."""
    while isinstance(service, (InstrumentedServiceProxy, TracingProxy)):
        service = object.__getattribute__(service, "_target")
    return service


class TTSFactory:
    """TTS service factory class"""

    @staticmethod
    def create(
        provider_type: str | None = None,
        *,
        strict: bool = False,
        observation_recorder: ObservationRecorder | None = None,
        **kwargs,
    ) -> TTSInterface:
        """
        Creates TTS instance by provider via ProviderRegistry.

        Args:
            provider_type: Registered provider type used to select the implementation
            strict: Reject unknown providers and propagate creation failures
            **kwargs: Parameters passed to build the config object

        Returns:
            TTSInterface: TTS instance

        Falls back to MockTTS on failure unless ``strict`` is enabled.
        """
        if provider_type is None:
            provider_type = kwargs.pop("provider", None)
        if not provider_type:
            raise ValueError("TTS provider type is required")
        config = TTSFactory._build_config(provider_type, kwargs, strict=strict)
        if config is None:
            if strict:
                raise ValueError(f"Unknown TTS provider: {provider_type}")
            logger.warning(f"Unknown TTS provider: {provider_type}, using Mock implementation")
            return instrument_service(
                MockTTS(), observation_recorder, "tts", provider="mock", model="mock"
            )

        try:
            module_name = {
                "mock": ".mock_tts",
                "edge": ".edge_tts",
                "edge_tts": ".edge_tts",
                "mimo": ".mimo_tts",
                "mimo_tts": ".mimo_tts",
                "mimo-tts": ".mimo_tts",
                "gpt_sovits": ".gpt_sovits_tts",
                "qwen3": ".qwen3_tts",
                "remote": ".remote_tts",
                "glm": ".contrib.glm_tts",
                "chattts": ".contrib.chattts_tts",
                "kokoro": ".contrib.kokoro_tts",
                "vibe_voice": ".contrib.vibe_voice_tts",
            }.get(provider_type)
            if module_name is not None:
                try:
                    import_module(module_name, __package__)
                except ImportError as exc:
                    if strict:
                        raise
                    logger.warning(
                        "TTS provider import unavailable: "
                        f"type={provider_type}, error={type(exc).__name__}"
                    )
            svc = ProviderRegistry.create_service("tts", config)
            if (
                strict
                and provider_type != "mock"
                and isinstance(_unwrap_tracing_proxy(svc), MockTTS)
            ):
                raise RuntimeError(
                    "Strict TTS provider creation returned MockTTS for a non-mock config"
                )
            return instrument_service(
                svc,
                observation_recorder,
                "tts",
                provider=provider_type,
                model=getattr(config, "model", None),
            )
        except Exception as e:
            if strict:
                logger.error(
                    "Strict TTS service creation failed: "
                    f"type={provider_type}, error={type(e).__name__}"
                )
                raise
            logger.warning(
                "TTS provider failed to initialize; falling back to MockTTS: "
                f"type={provider_type}, error={type(e).__name__}"
            )
            return instrument_service(
                MockTTS(), observation_recorder, "tts", provider="mock", model="mock"
            )

    @staticmethod
    def _build_config(provider: str, kwargs: dict, *, strict: bool = False):
        """Build a config Pydantic object from kwargs, or None if unknown."""
        try:
            if provider == "openai":
                return OpenAITTSConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "tts-1"),
                    voice=kwargs.get("voice", "alloy"),
                    base_url=kwargs.get("base_url"),
                )
            elif provider in ("edge", "edge_tts"):
                return EdgeTTSConfig(
                    voice=kwargs.get("voice", "zh-CN-XiaoxiaoNeural"),
                    rate=kwargs.get("rate"),
                    pitch=kwargs.get("pitch"),
                    preset=kwargs.get("preset"),
                )
            elif provider == "glm":
                return GLMTTSConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "glm-tts"),
                    voice=kwargs.get("voice", "female"),
                    response_format=kwargs.get("response_format", "wav"),
                    speed=kwargs.get("speed", 1.0),
                    volume=kwargs.get("volume", 1.0),
                )
            elif provider in ("mimo", "mimo_tts", "mimo-tts"):
                return MimoTTSConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "mimo-v2.5-tts"),
                    voice=kwargs.get("voice", "mimo_default"),
                    base_url=kwargs.get("base_url", "https://api.xiaomimimo.com/v1"),
                    response_format=kwargs.get("response_format", "wav"),
                    style_prompt=kwargs.get("style_prompt"),
                    timeout=kwargs.get("timeout", 60.0),
                )
            elif provider == "chattts":
                return ChatTTSConfig(
                    model_path=kwargs.get("model_path", "E:/anima_data/models/ChatTTS"),
                    device=kwargs.get("device", "cpu"),
                    compile=kwargs.get("compile", False),
                    speaker_seed=kwargs.get("speaker_seed", 42),
                    temperature=kwargs.get("temperature", 0.3),
                    top_p=kwargs.get("top_p", 0.7),
                    top_k=kwargs.get("top_k", 20),
                )
            elif provider == "kokoro":
                return KokoroTTSConfig(
                    voice=kwargs.get("voice", "zf_xiaobei"),
                    model_repo_id=kwargs.get("model_repo_id", "hexgrad/Kokoro-82M"),
                    model_path=kwargs.get("model_path"),
                    device=kwargs.get("device", "cuda"),
                    lang_code=kwargs.get("lang_code", "z"),
                    speed=kwargs.get("speed", 1.0),
                    glados_effect=kwargs.get("glados_effect"),
                )
            elif provider == "vibe_voice":
                return VibeVoiceTTSConfig(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "vibe-voice-1.5b"),
                    voice=kwargs.get("voice", "default"),
                    base_url=kwargs.get("base_url", "http://localhost:8765"),
                    mode=kwargs.get("mode", "remote"),
                    model_size=kwargs.get("model_size", "1.5b"),
                    model_path=kwargs.get("model_path"),
                    device=kwargs.get("device", "cuda:0"),
                    num_speakers=kwargs.get("num_speakers", 1),
                    language=kwargs.get("language", "zh"),
                )
            elif provider == "gpt_sovits":
                return GPTSoVITSConfig(
                    base_url=kwargs.get("base_url", "http://127.0.0.1:9880"),
                    ref_audio_path=kwargs.get("ref_audio_path", ""),
                    prompt_text=kwargs.get("prompt_text", ""),
                    prompt_lang=kwargs.get("prompt_lang", "zh"),
                    text_lang=kwargs.get("text_lang", "zh"),
                    top_k=kwargs.get("top_k", 15),
                    top_p=kwargs.get("top_p", 1.0),
                    temperature=kwargs.get("temperature", 1.0),
                    speed=kwargs.get("speed", 1.0),
                    media_type=kwargs.get("media_type", "wav"),
                    streaming_mode=kwargs.get("streaming_mode", False),
                    text_split_method=kwargs.get("text_split_method", "cut5"),
                    sample_steps=kwargs.get("sample_steps", 32),
                    seed=kwargs.get("seed", -1),
                    aux_ref_audio_paths=kwargs.get("aux_ref_audio_paths", []),
                )
            elif provider == "mock":
                return MockTTSConfig()
            elif provider == "qwen3":
                return Qwen3TTSConfig(
                    model=kwargs.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
                    revision=kwargs.get("revision"),
                    speaker=kwargs.get("speaker", "Vivian"),
                    device=kwargs.get("device", "cuda:0"),
                    dtype=kwargs.get("dtype", "bfloat16"),
                    default_instruct=kwargs.get("default_instruct", ""),
                    language=kwargs.get("language", "Chinese"),
                    max_new_tokens=kwargs.get("max_new_tokens", 4096),
                    top_p=kwargs.get("top_p", 0.9),
                    temperature=kwargs.get("temperature", 0.9),
                    repetition_penalty=kwargs.get("repetition_penalty", 1.05),
                    use_flash_attn=kwargs.get("use_flash_attn", True),
                    ref_audio_path=kwargs.get("ref_audio_path"),
                    ref_text=kwargs.get("ref_text"),
                    x_vector_only=kwargs.get("x_vector_only", True),
                )
            elif provider == "remote":
                return RemoteTTSConfig.model_validate({"type": "remote", **kwargs})
            else:
                return None
        except ImportError as e:
            if strict:
                raise
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get the stable catalog of providers with service implementations."""
        return list(_AVAILABLE_TTS_PROVIDERS)

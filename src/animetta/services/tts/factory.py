from __future__ import annotations

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
    GPTSoVITSConfig,
    KokoroTTSConfig,
    MockTTSConfig,
    OpenAITTSConfig,
    Qwen3TTSConfig,
    VibeVoiceTTSConfig,
)
from animetta.tracing.proxy import TracingProxy

from .interface import TTSInterface
from .mock_tts import MockTTS


class TTSFactory:
    """TTS service factory class"""

    @staticmethod
    def create(provider: str, **kwargs) -> TTSInterface:
        """
        Creates TTS instance by provider via ProviderRegistry.

        Args:
            provider: Provider name
            **kwargs: Parameters passed to build the config object

        Returns:
            TTSInterface: TTS instance

        Falls back to MockTTS on failure.
        """
        config = TTSFactory._build_config(provider, kwargs)
        if config is None:
            logger.warning(f"Unknown TTS provider: {provider}, using Mock implementation")
            return MockTTS()

        try:
            svc = ProviderRegistry.create_service("tts", config)
            return TracingProxy(svc, service_name="tts")
        except Exception as e:
            logger.warning(f"TTS provider '{provider}' failed to initialize: {e}, falling back to MockTTS")
            return MockTTS()

    @staticmethod
    def _build_config(provider: str, kwargs: dict):
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
            else:
                return None
        except ImportError as e:
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get list of all available providers"""
        return list(ProviderRegistry.list_services("tts"))

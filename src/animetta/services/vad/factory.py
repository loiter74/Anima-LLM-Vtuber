from __future__ import annotations

from animetta.config.core.registry import ProviderRegistry

"""
VAD Factory - Create VAD instances based on configuration
"""


from loguru import logger

from animetta.config.providers.vad import VADBaseConfig
from animetta.observability.service_proxy import instrument_service

from .interface import VADInterface
from .mock_vad import MockVAD


class VADFactory:
    """VAD Service Factory"""

    @staticmethod
    def create_from_config(
        config: VADBaseConfig,
        *,
        strict: bool = False,
        **kwargs,
    ) -> VADInterface:
        """
        Create VAD instance from config object (using ProviderRegistry)

        Args:
            config: VAD configuration object
            **kwargs: Additional parameters

        Returns:
            VADInterface: VAD instance

        Raises:
            ValueError: If no corresponding service implementation is found
        """
        try:
            vad = ProviderRegistry.create_service("vad", config)
            if strict and config.type != "mock" and isinstance(vad, MockVAD):
                raise RuntimeError(
                    "Strict VAD provider creation returned MockVAD for a non-mock config"
                )
            logger.info(f"VAD service created successfully: type={config.type}")
            return instrument_service(
                vad,
                kwargs.get("observation_recorder"),
                "vad",
                provider=config.type,
                model=getattr(config, "model", None),
            )
        except Exception as e:
            if strict:
                raise
            logger.error(
                f"Failed to create VAD service (type={config.type}): {type(e).__name__}: {e}"
            )
            # Degrade to Mock implementation
            logger.warning(f"Degraded to using MockVAD (original config: {config.type})")
            return instrument_service(
                MockVAD(
                    sample_rate=getattr(config, "sample_rate", 16000),
                    db_threshold=-30.0,
                    min_speech_duration=5,
                    min_silence_duration=15,
                ),
                kwargs.get("observation_recorder"),
                "vad",
                provider="mock",
                model="mock",
            )

    @staticmethod
    def create(provider: str, *, strict: bool = False, **kwargs) -> VADInterface:
        """
        Create VAD instance by provider

        Args:
            provider: Provider name
            **kwargs: Parameters passed to the implementation

        Returns:
            VADInterface: VAD instance

        Raises:
            ValueError: Unknown provider
        """
        normalized_provider = provider.replace("_", "-")
        if normalized_provider == "silero":
            try:
                from .silero_vad import SileroVAD

                return SileroVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                    prob_threshold=kwargs.get("prob_threshold", 0.15),
                    db_threshold=kwargs.get("db_threshold", -100),
                    required_hits=kwargs.get("required_hits", 6),
                    required_misses=kwargs.get("required_misses", 2),
                    smoothing_window=kwargs.get("smoothing_window", 12),
                )
            except ImportError as e:
                if strict:
                    raise
                logger.warning(f"silero-vad is not installed, falling back to Mock VAD: {e}")
                logger.info("Tip: Run 'pip install silero-vad' to install silero-vad")
                from .mock_vad import MockVAD

                return MockVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                    db_threshold=kwargs.get("db_threshold", -30.0),
                    min_speech_duration=kwargs.get("min_speech_duration", 5),
                    min_silence_duration=kwargs.get("min_silence_duration", 15),
                )
            except Exception as e:
                if strict:
                    raise
                logger.error(f"Failed to initialize Silero VAD, falling back to Mock VAD: {e}")
                from .mock_vad import MockVAD

                return MockVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                )
        elif normalized_provider in {"mimo", "mimo-vad"}:
            try:
                from .mimo_vad import MimoVAD

                return MimoVAD(
                    api_key=kwargs.get("api_key"),
                    model=kwargs.get("model", "mimo-v2.5-asr"),
                    base_url=kwargs.get("base_url", "https://api.xiaomimimo.com/v1"),
                    language=kwargs.get("language", "auto"),
                    audio_format=kwargs.get("audio_format", "wav"),
                    sample_rate=kwargs.get("sample_rate", 16000),
                    db_threshold=kwargs.get("db_threshold", -35.0),
                    min_speech_duration=kwargs.get("min_speech_duration", 2),
                    min_silence_duration=kwargs.get("min_silence_duration", 8),
                    confirm_with_asr=kwargs.get("confirm_with_asr", True),
                    timeout=kwargs.get("timeout", 15.0),
                    http_client=kwargs.get("http_client"),
                )
            except Exception as e:
                if strict:
                    raise
                logger.error(f"Failed to initialize MiMo VAD, falling back to Mock VAD: {e}")
                from .mock_vad import MockVAD

                return MockVAD(sample_rate=kwargs.get("sample_rate", 16000))
        elif normalized_provider == "mock":
            from .mock_vad import MockVAD

            return MockVAD(
                sample_rate=kwargs.get("sample_rate", 16000),
                db_threshold=kwargs.get("db_threshold", -30.0),
                min_speech_duration=kwargs.get("min_speech_duration", 5),
                min_silence_duration=kwargs.get("min_silence_duration", 15),
            )
        else:
            if strict:
                raise ValueError(f"Unknown VAD provider: {provider}")
            logger.warning(f"Unknown VAD provider: {provider}, using Mock implementation")
            from .mock_vad import MockVAD

            return MockVAD()

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get a list of all available providers"""
        return ["mock", "silero", "mimo-vad"]

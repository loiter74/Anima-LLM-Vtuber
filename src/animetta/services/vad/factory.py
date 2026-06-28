from __future__ import annotations

from animetta.config.core.registry import ProviderRegistry

"""
VAD Factory - Create VAD instances based on configuration
"""


from loguru import logger

from animetta.tracing.proxy import TracingProxy

from .interface import VADInterface
from .mock_vad import MockVAD


class VADFactory:
    """VAD Service Factory"""

    @staticmethod
    def create_from_config(config, **kwargs) -> VADInterface:
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
            logger.info(f"VAD service created successfully: type={config.type}")
            return TracingProxy(vad, service_name="vad")
        except Exception as e:
            logger.error(f"Failed to create VAD service (type={config.type}): {type(e).__name__}: {e}")
            # Degrade to Mock implementation
            logger.warning(f"Degraded to using MockVAD (original config: {config.type})")
            return MockVAD(
                sample_rate=getattr(config, 'sample_rate', 16000),
                db_threshold=-30.0,
                min_speech_duration=5,
                min_silence_duration=15,
            )

    @staticmethod
    def create(provider: str, **kwargs) -> VADInterface:
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
        if provider == "silero":
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
                logger.error(f"Failed to initialize Silero VAD, falling back to Mock VAD: {e}")
                from .mock_vad import MockVAD
                return MockVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                )
        elif provider == "mock":
            from .mock_vad import MockVAD
            return MockVAD(
                sample_rate=kwargs.get("sample_rate", 16000),
                db_threshold=kwargs.get("db_threshold", -30.0),
                min_speech_duration=kwargs.get("min_speech_duration", 5),
                min_silence_duration=kwargs.get("min_silence_duration", 15),
            )
        else:
            logger.warning(f"Unknown VAD provider: {provider}, using Mock implementation")
            from .mock_vad import MockVAD
            return MockVAD()

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get a list of all available providers"""
        return ["mock", "silero"]

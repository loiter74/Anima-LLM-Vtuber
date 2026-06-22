from __future__ import annotations

"""
Separation Factory - creates Separation instances based on configuration
"""


from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.separation import DemucsSeparationConfig, MockSeparationConfig
from animetta.tracing.proxy import TracingProxy

from .interface import SeparationInterface
from .mock_separation import MockSeparation


class SeparationFactory:
    """Separation service factory class"""

    @staticmethod
    def create(provider: str, **kwargs) -> SeparationInterface:
        """
        Creates Separation instance by provider via ProviderRegistry.

        Args:
            provider: Provider name (demucs, mock, etc.)
            **kwargs: Parameters passed to build the config object

        Returns:
            SeparationInterface: Separation instance
        """
        config = SeparationFactory._build_config(provider, kwargs)
        if config is None:
            logger.warning(f"Unknown Separation provider: {provider}, using Mock implementation")
            return MockSeparation()

        try:
            svc = ProviderRegistry.create_service("separation", config)
            return TracingProxy(svc, service_name="separation")
        except Exception as e:
            logger.warning(f"Failed to create Separation ({provider}): {e}, falling back to Mock")
            return MockSeparation()

    @staticmethod
    def _build_config(provider: str, kwargs: dict):
        """Build a config Pydantic object from kwargs, or None if unknown."""
        try:
            if provider == "demucs":
                return DemucsSeparationConfig(
                    model_type=kwargs.get("model_type", "mel_band_roformer"),
                    config_path=kwargs.get("config_path", ""),
                    checkpoint_path=kwargs.get("checkpoint_path", ""),
                    device=kwargs.get("device", "cuda:0"),
                    chunk_size=kwargs.get("chunk_size", 131584),
                    num_overlap=kwargs.get("num_overlap", 4),
                    batch_size=kwargs.get("batch_size", 1),
                    normalize=kwargs.get("normalize", True),
                    is_half=kwargs.get("is_half", True),
                    sample_rate=kwargs.get("sample_rate", 44100),
                    instruments=kwargs.get("instruments", ["vocals", "other"]),
                    primary_stem=kwargs.get("primary_stem"),
                )
            elif provider == "mock":
                return MockSeparationConfig()
            else:
                return None
        except ImportError as e:
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get list of all available providers"""
        return list(ProviderRegistry.list_services("separation"))

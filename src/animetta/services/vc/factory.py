from __future__ import annotations

"""
VC Factory - creates VC instances based on configuration
"""


from loguru import logger

from animetta.core.config.core.registry import ProviderRegistry
from animetta.core.config.providers.vc import MockVCConfig, RVCConfig
from animetta.tracing.proxy import TracingProxy

from .interface import VCInterface
from .mock_vc import MockVC


class VCFactory:
    """VC service factory class"""

    @staticmethod
    def create(provider: str, **kwargs) -> VCInterface:
        """
        Creates VC instance by provider via ProviderRegistry.

        Args:
            provider: Provider name (rvc, mock, etc.)
            **kwargs: Parameters passed to build the config object

        Returns:
            VCInterface: VC instance
        """
        config = VCFactory._build_config(provider, kwargs)
        if config is None:
            logger.warning(f"Unknown VC provider: {provider}, using Mock implementation")
            return MockVC()

        try:
            svc = ProviderRegistry.create_service("vc", config)
            return TracingProxy(svc, service_name="vc")
        except Exception as e:
            logger.warning(f"Failed to create VC ({provider}): {e}, falling back to Mock")
            return MockVC()

    @staticmethod
    def _build_config(provider: str, kwargs: dict):
        """Build a config Pydantic object from kwargs, or None if unknown."""
        try:
            if provider == "rvc":
                return RVCConfig(
                    model_path=kwargs.get("model_path", ""),
                    index_path=kwargs.get("index_path", ""),
                    index_rate=kwargs.get("index_rate", 0.0),
                    f0_method=kwargs.get("f0_method", "rmvpe"),
                    key=kwargs.get("key", 0),
                    formant=kwargs.get("formant", 0),
                    device=kwargs.get("device", "cuda:0"),
                    is_half=kwargs.get("is_half", True),
                    rms_mix_rate=kwargs.get("rms_mix_rate", 1.0),
                    protect=kwargs.get("protect", 0.33),
                    hop_length=kwargs.get("hop_length", 128),
                    f0_min=kwargs.get("f0_min", 50),
                    f0_max=kwargs.get("f0_max", 1100),
                    sample_rate=kwargs.get("sample_rate", 40000),
                )
            elif provider == "mock":
                return MockVCConfig()
            else:
                return None
        except ImportError as e:
            logger.warning(f"Config class not available for {provider}: {e}")
            return None

    @staticmethod
    def get_available_configs() -> list[str]:
        """Get list of all available providers"""
        return list(ProviderRegistry.list_services("vc"))

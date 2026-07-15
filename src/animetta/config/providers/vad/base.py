"""VAD base configuration"""

from ...core.base import ProviderConfig


class VADBaseConfig(ProviderConfig):
    """VAD configuration base class"""

    sample_rate: int = 16000

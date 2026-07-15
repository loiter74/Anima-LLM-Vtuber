"""Audio Source Separation base configuration"""

from pydantic import Field

from ...core.base import ProviderConfig
from ...core.mixins import DeviceMixin


class SeparationBaseConfig(ProviderConfig, DeviceMixin):
    """
    Audio Source Separation provider configuration base class

    All separation provider configurations should inherit from this class.
    Source separation decomposes an audio mixture into its constituent
    stems (e.g., vocals, drums, bass, other).
    """

    sample_rate: int = Field(default=44100, description="Target sample rate for processing")

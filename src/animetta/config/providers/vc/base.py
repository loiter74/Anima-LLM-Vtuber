"""Voice Conversion (VC) base configuration"""

from pydantic import Field

from ...core.base import ProviderConfig
from ...core.mixins import DeviceMixin


class VCBaseConfig(ProviderConfig, DeviceMixin):
    """
    Voice Conversion provider configuration base class

    All VC provider configurations should inherit from this class.
    Voice conversion transforms the timbre of an input audio while
    preserving the linguistic content.
    """

    is_half: bool = Field(default=True, description="Use FP16 half precision for inference")

"""ASR base configuration"""

from pydantic import Field

from ...core.base import ProviderConfig
from ...core.mixins import ApiKeyMixin, ModelMixin


class ASRBaseConfig(ProviderConfig, ApiKeyMixin, ModelMixin):
    """
    ASR provider configuration base class

    All ASR provider configurations should inherit from this class
    """

    language: str = Field(default="zh", description="Recognition language")

"""Reusable Mixin classes for composing provider config base classes.

Each Mixin defines 1-2 commonly shared fields to eliminate duplication
across provider category base classes. Mixins are Pydantic model fragments —
inherit them alongside ProviderConfig to compose a complete base class.

Usage:
    class LLMBaseConfig(ProviderConfig, ApiKeyMixin, ModelMixin, TemperatureMixin):
        pass  # All common fields come from Mixins
"""

import warnings

from pydantic import Field

# Provider configs intentionally re-declare mixin fields (``model``, ``base_url``,
# ``temperature``, ``top_p``) to supply provider-specific defaults like
# ``model="deepseek-chat"`` or ``base_url="http://localhost:8765"``. Pydantic V2
# emits a ``UserWarning`` for every such override (30+ providers × 1-3 fields =
# hundreds of warnings per test run). The override is deliberate and safe — the
# subclass default wins, exactly as intended — so silence the noise here, at the
# single source of the inherited fields, rather than per-provider.
# If a future change makes a shadow unintentional, remove this filter to surface it.
warnings.filterwarnings(
    "ignore",
    message=r".*shadows an attribute in parent.*",
    category=UserWarning,
)


class ApiKeyMixin:
    """Mixin for providers requiring API key authentication.

    Composed into: LLMBaseConfig, ASRBaseConfig, TTSBaseConfig
    """

    api_key: str | None = Field(
        default=None, description="API Key for cloud provider authentication"
    )


class ModelMixin:
    """Mixin for providers with a model selection and optional custom endpoint.

    Composed into: LLMBaseConfig, ASRBaseConfig, TTSBaseConfig
    """

    model: str = Field(default="", description="Model identifier (provider-specific)")
    base_url: str | None = Field(default=None, description="Override API base URL")


class DeviceMixin:
    """Mixin for providers running on local GPU/CPU hardware.

    Composed into: VCBaseConfig, SeparationBaseConfig.
    Also used by individual provider implementations (chattts, kokoro, vibe_voice, funasr, etc.).
    """

    device: str = Field(default="cuda:0", description="Device for inference (cuda:0 / cpu / auto)")


class TemperatureMixin:
    """Mixin for LLM providers with generation temperature and token limit.

    Composed into: LLMBaseConfig
    """

    temperature: float = Field(
        default=0.7, ge=0, le=2, description="Generation temperature (higher = more creative)"
    )
    top_p: float = Field(default=0.9, ge=0, le=1, description="Nucleus sampling parameter")
    max_tokens: int = Field(default=4096, ge=1, description="Maximum generated tokens")
    max_history_messages: int = Field(
        default=20, ge=0, description="Max messages retained in provider history (0=unbounded)"
    )

"""ChatTTS provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "chattts")
class ChatTTSConfig(TTSBaseConfig):
    """ChatTTS configuration (open-source conversational TTS)"""

    type: Literal["chattts"] = "chattts"
    model_path: str = Field(default="E:/models/ChatTTS", description="Model file storage path")
    device: str = Field(default="cpu", description="Inference device: cuda / cpu")
    compile: bool = Field(
        default=False,
        description="Whether to enable torch.compile (recommended to disable on Windows)",
    )
    speaker_seed: int | None = Field(
        default=42,
        description="Speaker timbre seed, fixed for consistent voice generation; set to None for random",
    )
    temperature: float = Field(
        default=0.3,
        description="Generation temperature, lower is more stable, higher is more expressive",
    )
    top_p: float = Field(default=0.7, description="Nucleus sampling parameter")
    top_k: int = Field(default=20, description="Top-k sampling parameter")

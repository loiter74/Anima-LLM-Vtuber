"""Qwen3-TTS provider configuration (通义千问 Qwen3-TTS)"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "qwen3")
class Qwen3TTSConfig(TTSBaseConfig):
    """Qwen3-TTS configuration

    Local inference mode using qwen-tts package.
    Loads 1.7B CustomVoice model (~3.5GB VRAM bfloat16) via HuggingFace.
    Supports 9 preset voices + zero-shot voice clone via ref_audio_path.

    GPU requirements: ~4-6GB VRAM for bfloat16, ~3-4GB for float16.
    Windows CUDA note: bfloat16 may need auto-fallback to float16 on some GPUs.
    """

    type: Literal["qwen3"] = "qwen3"

    # === Model identifier ===
    model: str = Field(
        default="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        description="HuggingFace model ID or local directory path",
    )
    revision: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Optional exact local Hugging Face snapshot revision",
    )

    # === Inference device ===
    device: str = Field(
        default="cuda:0",
        description="Inference device: cuda:0 / cpu",
    )
    dtype: str = Field(
        default="bfloat16",
        description='Model dtype: "bfloat16" / "float16". Use float16 if GPU lacks bf16 support (e.g., GTX 16xx)',
    )

    # === Synthesis parameters ===
    speaker: str = Field(
        default="Vivian",
        description="Preset speaker voice name (9 premium timbres available)",
    )
    default_instruct: str = Field(
        default="",
        description="Default instruction for emotion/style control (e.g., '用温柔的语气说'). Overridable at synthesize() call time.",
    )
    language: str = Field(
        default="Chinese",
        description="Language: Chinese / English / Japanese / Korean / German / French / Russian / Portuguese / Spanish / Italian",
    )
    max_new_tokens: int = Field(
        default=4096,
        ge=32,
        le=16384,
        description="Maximum audio tokens to generate (32 is about 2.7 seconds at 12 Hz)",
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Top-p nucleus sampling probability",
    )
    temperature: float = Field(
        default=0.9,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    repetition_penalty: float = Field(
        default=1.05,
        ge=1.0,
        le=2.0,
        description="Repetition penalty for token generation",
    )

    # === Flash Attention ===
    use_flash_attn: bool = Field(
        default=True,
        description="Use FlashAttention 2 for optimized GPU memory usage. Silently falls back if not installed.",
    )

    # === Voice Clone ===
    ref_audio_path: str | None = Field(
        default=None,
        description="Path to reference audio WAV for voice clone mode. When set, synthesize() uses generate_voice_clone() instead of generate_custom_voice().",
    )
    ref_text: str | None = Field(
        default=None,
        description="Reference transcript for ICL mode (required when x_vector_only=False). Optional when x_vector_only=True.",
    )
    x_vector_only: bool = Field(
        default=True,
        description="If True, use speaker embedding only (no ref_text needed). If False, ICL mode with ref_text + speech codes.",
    )

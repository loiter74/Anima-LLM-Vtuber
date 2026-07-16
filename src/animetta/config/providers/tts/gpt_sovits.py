"""GPT-SoVITS TTS provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "gpt_sovits")
class GPTSoVITSConfig(TTSBaseConfig):
    """GPT-SoVITS TTS configuration

    Connects to a locally running GPT-SoVITS api_v2.py server via REST API.
    Supports few-shot voice cloning with reference audio and configurable inference parameters.
    """

    type: Literal["gpt_sovits"] = "gpt_sovits"

    # === Server connection ===
    base_url: str = Field(
        default="http://127.0.0.1:9880",
        description="GPT-SoVITS api_v2.py server URL",
    )

    # === Reference audio (required) ===
    ref_audio_path: str = Field(
        default="",
        description="Path to reference audio file on the server (required)",
    )
    prompt_text: str = Field(
        default="",
        description="Transcript of the reference audio (required)",
    )
    prompt_lang: str = Field(
        default="zh",
        description="Language of prompt text: zh / en / ja / ko / yue / auto",
    )
    text_lang: str = Field(
        default="zh",
        description="Language of text to synthesize: zh / en / ja / ko / yue / auto",
    )

    # === Inference parameters ===
    top_k: int = Field(
        default=15,
        ge=1,
        le=100,
        description="Top-k sampling parameter",
    )
    top_p: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Top-p sampling parameter",
    )
    temperature: float = Field(
        default=1.0,
        ge=0.1,
        le=2.0,
        description="Sampling temperature",
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speed factor (speed_factor in GPT-SoVITS API)",
    )
    media_type: str = Field(
        default="wav",
        description="Audio output format: wav / ogg / aac / raw",
    )
    streaming_mode: bool = Field(
        default=False,
        description="Enable streaming mode (0=disabled, 1/2/3=enabled)",
    )
    text_split_method: str = Field(
        default="cut5",
        description="Text segmentation method: cut0 / cut1 / cut2 / cut3 / cut4 / cut5",
    )
    sample_steps: int = Field(
        default=32,
        ge=4,
        le=128,
        description="Sampling steps for V3/V4 models (4/8/16/32/64/128)",
    )
    seed: int = Field(
        default=-1,
        description="Random seed for reproducibility (-1 for random)",
    )
    aux_ref_audio_paths: list = Field(
        default=[],
        description="Auxiliary reference audio paths for multi-speaker tone fusion",
    )

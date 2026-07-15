"""Kokoro TTS provider configuration"""

from typing import Any, Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig

# Default GLaDOS effect chain parameters
# Based on SoX effects chain for electronic/robotic voice:
# pitch → stretch → overdrive → chorus → bandpass → compand → gain
DEFAULT_GLADOS_EFFECTS: dict[str, Any] = {
    "enabled": True,
    "pitch": -300,  # cents: lower = more deep/masculine
    "stretch": 1.05,  # ratio: >1 = slower, more deliberate
    "overdrive": 20,  # gain dB: distortion intensity
    "chorus": "0.7 0.9 55 0.4 0.25 2 -t",  # SoX chorus params
    "bandpass": "300 3",  # center_hz Q: bandpass filter
    "compand": "0.3,1 6:-70,-60,-20 -5 -90 0.2",  # SoX compand params
    "gain": -3,  # dB: output level adjustment
}


@ProviderRegistry.register_config("tts", "kokoro")
class KokoroTTSConfig(TTSBaseConfig):
    """
    Kokoro TTS configuration (open-weight multilingual TTS)

    Kokoro is an 82M parameter StyleTTS2-based model supporting
    Chinese (Mandarin) and English. Models auto-download from HuggingFace.

    https://github.com/hexgrad/kokoro
    """

    type: Literal["kokoro"] = "kokoro"
    voice: str = Field(
        default="zf_xiaobei",
        description="Voice name. Chinese: zf_xiaobei/female, zf_xiaoni/female, "
        "zf_xiaoxiao/female, zf_xiaoyi/female, "
        "zm_yunjian/male, zm_yunxi/male, zm_yunxia/male, zm_yunyang/male. "
        "English: af_bella/female, am_adam/male, etc.",
    )
    model_repo_id: str = Field(
        default="hexgrad/Kokoro-82M",
        description="HuggingFace repo ID for model weights and voice packs",
    )
    model_path: str | None = Field(
        default=None, description="Local path to model checkpoint. If None, downloads from HF."
    )
    device: str = Field(
        default="cuda",
        description="Device for inference: 'cuda' (preferred), 'cpu' (fallback), or None for auto-select",
    )
    lang_code: str = Field(
        default="z",
        description="Language code: 'z'=Mandarin Chinese, 'a'=US English, 'b'=British English",
    )
    glados_effect: dict[str, Any] | None = Field(
        default=None,
        description=(
            "GLaDOS-style audio effect parameters. Set to a dict with effect params "
            "to enable electronic voice processing. Keys: enabled, pitch, stretch, "
            "overdrive, chorus, bandpass, compand, gain. "
            "Set glados_effect={'enabled': False} to disable."
        ),
    )

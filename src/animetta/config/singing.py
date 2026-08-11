"""Singing module Pydantic configuration."""

import os
import re

from pydantic import BaseModel, Field, field_validator

_ENV_TEMPLATE = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*):(.*)\}$")


def _expand_env_template(value: object) -> object:
    if not isinstance(value, str):
        return value
    match = _ENV_TEMPLATE.fullmatch(value)
    if match is None:
        return value
    name, default = match.groups()
    return os.getenv(name, default)


class GPTSoVITSConfig(BaseModel):
    base_url: str = "http://127.0.0.1:9880"
    svc_endpoint: str = "/svc"
    ref_audio_path: str = ""
    prompt_text: str = ""
    text_lang: str = "zh"
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0
    text_split_method: str = "cut5"


class BilibiliConfig(BaseModel):
    downloader: str = "yt-dlp"
    output_dir: str = "./data/singing/downloads"


class SeparationConfig(BaseModel):
    engine: str = "demucs"  # "demucs" or "uvr"
    fallback_engine: str = "ffmpeg"
    model: str = "htdemucs"
    output_dir: str = "./data/singing/separated"
    base_url: str = ""
    api_key_env: str = "QWEN_TTS_API_KEY"
    request_timeout_seconds: float = Field(default=1200.0, gt=0)

    @field_validator("base_url", mode="before")
    @classmethod
    def expand_environment_url(cls, value: object) -> object:
        return _expand_env_template(value)


class ASRConfig(BaseModel):
    model_size: str = "large-v3"
    language: str | None = "zh"
    output_dir: str = "./data/singing/lyrics"
    download_root: str = "E:/anima_data/models/whisper"


class SVCConfig(BaseModel):
    output_dir: str = "./data/singing/converted"


class RVCConfig(BaseModel):
    enabled: bool = False
    required: bool = False
    base_url: str = ""
    api_key_env: str = "QWEN_TTS_API_KEY"
    expected_revision: str = ""
    request_timeout_seconds: float = Field(default=1200.0, gt=0)
    rvc_path: str = r"C:\Users\30262\RVC20240604Nvidia"
    python_exe: str = ""
    model_name: str = "kikiV1.pth"
    index_path: str = "logs/kikiV1.index"
    f0_method: str = "rmvpe"
    f0_up_key: int = 0
    index_rate: float = 0.75
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect: float = 0.33

    @field_validator("base_url", "rvc_path", "python_exe", mode="before")
    @classmethod
    def expand_environment_paths(cls, value: object) -> object:
        return _expand_env_template(value)


class SingingConfig(BaseModel):
    gpt_sovits: GPTSoVITSConfig = Field(default_factory=GPTSoVITSConfig)
    bilibili: BilibiliConfig = Field(default_factory=BilibiliConfig)
    separation: SeparationConfig = Field(default_factory=SeparationConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    svc: SVCConfig = Field(default_factory=SVCConfig)
    rvc: RVCConfig = Field(default_factory=RVCConfig)
    output_dir: str = "./data/singing/outputs"
    max_file_age_days: int = 7

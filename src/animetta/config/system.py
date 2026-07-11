"""System configuration"""

from typing import Literal

from pydantic import Field

from .core.base import BaseConfig


class SystemConfig(BaseConfig):
    """System configuration"""
    host: str = Field(default="localhost", description="Server address")
    port: int = Field(default=12394, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Log level")
    runtime_profile: Literal["development", "test", "golden"] = Field(
        default="development",
        description="Runtime behavior profile",
    )
    long_term_memory_mode: Literal["off", "read_only", "read_write"] = Field(
        default="off",
        description="Long-term memory access policy",
    )
    enable_tools: bool = Field(
        default=True,
        description="Allow tool execution paths",
    )
    enable_subtitle_translation: bool = Field(
        default=True,
        description="Allow subtitle translation paths",
    )
    enable_active_memes: bool = Field(
        default=True,
        description="Allow active meme generation paths",
    )
    golden_tts_timeout_seconds: float = Field(
        default=20.0, ge=1.0, le=60.0,
        description="Per-turn Qwen synthesis timeout in the golden profile",
    )
    gpt_sovits: dict = Field(default={}, description="GPT-SoVITS server path, python, port config")

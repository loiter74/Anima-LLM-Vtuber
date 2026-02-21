"""Faster-Whisper ASR 提供者配置"""

from typing import Literal, Optional
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register("asr", "faster_whisper")
class FasterWhisperASRConfig(ASRBaseConfig):
    """Faster-Whisper ASR 配置"""
    type: Literal["faster_whisper"] = "faster_whisper"

    # 模型配置
    model: str = Field(
        default="distil-large-v3",
        description="Whisper 模型名称 (tiny/base/small/medium/large-v2/large-v3/distil-*)"
    )

    language: str = Field(
        default="zh",
        description="语言代码 (zh=中文, en=英文, ja=日语, etc.)"
    )

    # 设备和性能配置
    device: str = Field(
        default="auto",
        description="运行设备 (auto/cpu/cuda)"
    )

    compute_type: str = Field(
        default="default",
        description="计算精度 (default/int8/float16/float32)"
    )

    download_root: Optional[str] = Field(
        default=None,
        description="模型下载目录"
    )

    # 识别参数
    beam_size: int = Field(
        default=5,
        ge=1,
        le=10,
        description="束搜索大小"
    )

    vad_filter: bool = Field(
        default=True,
        description="是否使用 VAD 过滤"
    )

    vad_parameters: dict = Field(
        default_factory=lambda: {
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 30,
        },
        description="VAD 参数"
    )

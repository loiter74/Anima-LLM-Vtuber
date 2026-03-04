"""
本地 LoRA LLM 配置
Local Lora LLM Configuration
"""

from typing import Optional, Literal
from pydantic import Field

from .base import LLMBaseConfig


class LocalLoraLLMConfig(LLMBaseConfig):
    """
    本地 LoRA 微调模型配置
    """

    type: Literal["local_lora"] = "local_lora"

    # 模型配置
    model: str = Field(
        default="local-lora-model",
        description="模型标识符"
    )

    base_model_name: str = Field(
        default="Qwen/Qwen2.5-7B-Instruct",
        description="基座模型名称"
    )

    lora_path: str = Field(
        default="models/lora/neuro-vtuber-v1",
        description="LoRA 适配器路径"
    )

    device: str = Field(
        default="cuda",
        description="计算设备 (cuda/cpu)"
    )

    # 可选参数
    max_new_tokens: int = Field(
        default=512,
        description="最大生成 token 数"
    )

    temperature: float = Field(
        default=0.7,
        description="生成温度参数"
    )

    top_p: float = Field(
        default=0.9,
        description="Top-p 采样参数"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "type": "local_lora",
                "base_model_name": "Qwen/Qwen2.5-7B-Instruct",
                "lora_path": "models/lora/neuro-vtuber-v1",
                "device": "cuda",
                "max_new_tokens": 512,
                "temperature": 0.7,
                "top_p": 0.9
            }
        }

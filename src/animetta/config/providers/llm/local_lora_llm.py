"""
Local LoRA LLM configuration
Local Lora LLM Configuration
"""

from typing import Literal

from pydantic import ConfigDict, Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "local_lora")
class LocalLoraLLMConfig(LLMBaseConfig):
    """
    Local LoRA fine-tuned model configuration
    """

    type: Literal["local_lora"] = "local_lora"

    # Model configuration
    model: str = Field(default="local-lora-model", description="Model identifier")

    base_model_name: str = Field(default="Qwen/Qwen2.5-7B-Instruct", description="Base model name")

    lora_path: str = Field(default="models/lora/neuro-vtuber-v1", description="LoRA adapter path")

    device: str = Field(default="cuda", description="Compute device (cuda/cpu)")

    # Optional parameters
    max_new_tokens: int = Field(default=512, description="Maximum generated tokens")

    top_p: float = Field(default=0.9, description="Top-p sampling parameter")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "local_lora",
                "base_model_name": "Qwen/Qwen2.5-7B-Instruct",
                "lora_path": "models/lora/neuro-vtuber-v1",
                "device": "cuda",
                "max_new_tokens": 512,
                "temperature": 0.7,
                "top_p": 0.9,
            }
        }
    )

"""
Mock ASR 实现 - 用于测试和开发
"""

from typing import Union
from pathlib import Path

from ..interface import ASRInterface
from ....config.core.registry import ProviderRegistry
from ....config.providers.asr.mock import MockASRConfig


@ProviderRegistry.register_service("asr", "mock")
class MockASR(ASRInterface):
    """
    Mock ASR 实现
    不进行实际的语音识别，返回固定的模拟文本
    """

    def __init__(self, mock_response: str = "这是一条模拟的语音识别结果"):
        self.mock_response = mock_response

    async def transcribe(
        self,
        audio_data: Union[bytes, str, Path],
        **kwargs
    ) -> str:
        """返回模拟的识别结果"""
        # 模拟处理延迟
        import asyncio
        await asyncio.sleep(0.1)
        
        # 如果是文件路径，可以记录一下
        if isinstance(audio_data, (str, Path)):
            return f"[Mock ASR] 音频文件 {audio_data} 的识别结果: {self.mock_response}"
        
        return self.mock_response

    async def close(self) -> None:
        """无需清理资源"""
        pass
"""
Mock TTS 实现 - 用于测试和开发
"""

from typing import Union, Optional
from pathlib import Path

from ..interface import TTSInterface
from ....config.core.registry import ProviderRegistry
from ....config.providers.tts.mock import MockTTSConfig


@ProviderRegistry.register_service("tts", "mock")
class MockTTS(TTSInterface):
    """
    Mock TTS 实现
    不进行实际的语音合成，返回模拟的音频路径
    """

    def __init__(self, mock_audio_path: str = "/cache/mock_audio.wav"):
        self.mock_audio_path = mock_audio_path

    async def synthesize(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        **kwargs
    ) -> Union[bytes, str]:
        """返回模拟的音频路径"""
        # 模拟处理延迟
        import asyncio
        await asyncio.sleep(0.1)
        
        if output_path:
            # 如果指定了输出路径，返回该路径
            return str(output_path)
        
        # 否则返回模拟路径
        return self.mock_audio_path

    async def close(self) -> None:
        """无需清理资源"""
        pass
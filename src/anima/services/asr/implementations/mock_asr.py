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
    不进行实际的语音识别，返回模拟的语音识别结果
    """

    # 测试用的模拟文本列表
    TEST_PHRASES = [
        "你好，请问你能帮我做什么？",
        "今天天气怎么样？",
        "我想听一首歌。",
        "讲个笑话给我听吧。",
        "你能告诉我现在几点了吗？",
        "我想了解人工智能的发展历史。",
        "推荐一些好看的电影给我。",
        "帮我写一封邮件。",
        "介绍一下你自己。",
        "今天过得怎么样？"
    ]

    def __init__(self, mock_response: str = None):
        # 如果没有指定响应，从列表中随机选择
        if mock_response is None:
            import random
            mock_response = random.choice(self.TEST_PHRASES)
        self.mock_response = mock_response

    async def transcribe(
        self,
        audio_data: Union[bytes, str, Path],
        **kwargs
    ) -> str:
        """返回模拟的识别结果"""
        # 模拟处理延迟（根据音频长度）
        import asyncio
        import random

        # 根据音频数据大小模拟不同的处理时间
        if isinstance(audio_data, bytes):
            audio_length = len(audio_data)
            delay = min(0.5, audio_length / 32000)  # 约 0.1-0.5 秒
        else:
            delay = 0.3

        await asyncio.sleep(delay)

        # 每次随机返回不同的测试文本（模拟真实语音输入的变化）
        response = random.choice(self.TEST_PHRASES)

        # 添加日志
        from loguru import logger
        logger.info(f"[Mock ASR] 返回模拟识别结果: {response}")

        return response

    async def close(self) -> None:
        """无需清理资源"""
        pass
from __future__ import annotations

"""
Mock ASR implementation - for testing and development
"""

from pathlib import Path

from animetta.config.core.registry import ProviderRegistry

from .interface import ASRInterface


@ProviderRegistry.register_service("asr", "mock")
class MockASR(ASRInterface):
    """
    Mock ASR implementation
    Does not perform actual speech recognition, returns simulated recognition results
    """

    # Test mock text list
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
        # If no response specified, pick randomly from the list
        if mock_response is None:
            import random
            mock_response = random.choice(self.TEST_PHRASES)
        self.mock_response = mock_response

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration (supports ProviderRegistry.create_service path)"""
        return cls()

    async def transcribe(
        self,
        audio_data: bytes | str | Path,
        **kwargs
    ) -> str:
        """Return simulated recognition result"""
        # Simulate processing delay (based on audio length)
        import asyncio
        import random

        # Simulate different processing times based on audio data size
        if isinstance(audio_data, bytes):
            audio_length = len(audio_data)
            delay = min(0.5, audio_length / 32000)  # Approximately 0.1-0.5 seconds
        else:
            delay = 0.3

        await asyncio.sleep(delay)

        # Randomly return different test text each time (simulates real voice input variation)
        response = random.choice(self.TEST_PHRASES)

        # Add log
        from loguru import logger
        logger.info(f"[Mock ASR] Returning simulated recognition result: {response}")

        return response

    async def close(self) -> None:
        """No resources to clean up"""
        pass

"""
TTS 工厂 - 根据配置创建 TTS 实例
"""

from typing import List
from loguru import logger

from .interface import TTSInterface


class TTSFactory:
    """TTS 服务工厂类"""
    
    @staticmethod
    def create(provider: str, **kwargs) -> TTSInterface:
        """
        根据提供商创建 TTS 实例
        
        Args:
            provider: 提供商名称
            **kwargs: 传递给具体实现的参数
            
        Returns:
            TTSInterface: TTS 实例
        """
        if provider == "openai":
            from .implementations.openai_tts import OpenAITTS
            return OpenAITTS(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "tts-1"),
                voice=kwargs.get("voice", "alloy"),
                base_url=kwargs.get("base_url")
            )
        elif provider == "edge_tts":
            from .implementations.edge_tts import EdgeTTS
            return EdgeTTS(voice=kwargs.get("voice"))
        elif provider == "glm":
            from .implementations.glm_tts import GLMTTS
            return GLMTTS(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "glm-tts"),
                voice=kwargs.get("voice", "female"),
                response_format=kwargs.get("response_format", "wav"),
                speed=kwargs.get("speed", 1.0),
                volume=kwargs.get("volume", 1.0)
            )
        elif provider == "mock":
            from .implementations.mock_tts import MockTTS
            return MockTTS()
        else:
            logger.warning(f"未知的 TTS 提供商: {provider}，使用 Mock 实现")
            from .implementations.mock_tts import MockTTS
            return MockTTS()
    
    @staticmethod
    def get_available_providers() -> List[str]:
        """获取所有可用的提供商列表"""
        return ["mock", "openai", "edge_tts", "glm"]

"""
VAD 工厂 - 根据配置创建 VAD 实例
"""

from typing import List
from loguru import logger

from .interface import VADInterface


class VADFactory:
    """VAD 服务工厂类"""
    
    @staticmethod
    def create(provider: str, **kwargs) -> VADInterface:
        """
        根据提供商创建 VAD 实例
        
        Args:
            provider: 提供商名称
            **kwargs: 传递给具体实现的参数
            
        Returns:
            VADInterface: VAD 实例
            
        Raises:
            ValueError: 未知的提供商
        """
        if provider == "silero":
            from .implementations.silero_vad import SileroVAD
            return SileroVAD(
                sample_rate=kwargs.get("sample_rate", 16000),
                prob_threshold=kwargs.get("prob_threshold", 0.4),
                db_threshold=kwargs.get("db_threshold", 60),
                required_hits=kwargs.get("required_hits", 3),
                required_misses=kwargs.get("required_misses", 24),
                smoothing_window=kwargs.get("smoothing_window", 5),
            )
        elif provider == "mock":
            from .implementations.mock_vad import MockVAD
            return MockVAD(
                sample_rate=kwargs.get("sample_rate", 16000),
                db_threshold=kwargs.get("db_threshold", -30.0),
                min_speech_duration=kwargs.get("min_speech_duration", 5),
                min_silence_duration=kwargs.get("min_silence_duration", 15),
            )
        else:
            logger.warning(f"未知的 VAD 提供商: {provider}，使用 Mock 实现")
            from .implementations.mock_vad import MockVAD
            return MockVAD()
    
    @staticmethod
    def get_available_providers() -> List[str]:
        """获取所有可用的提供商列表"""
        return ["mock", "silero"]
"""
ASR 工厂 - 根据配置创建 ASR 实例
"""

from typing import Type, List
from loguru import logger

from .interface import ASRInterface


class ASRFactory:
    """ASR 服务工厂类"""
    
    @staticmethod
    def create(provider: str, **kwargs) -> ASRInterface:
        """
        根据提供商创建 ASR 实例
        
        Args:
            provider: 提供商名称
            **kwargs: 传递给具体实现的参数
            
        Returns:
            ASRInterface: ASR 实例
            
        Raises:
            ValueError: 未知的提供商
        """
        if provider == "openai":
            from .implementations.openai_asr import OpenAIASR
            return OpenAIASR(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "whisper-1"),
                language=kwargs.get("language", "zh"),
                base_url=kwargs.get("base_url")
            )
        elif provider == "funasr":
            from .implementations.fun_asr import FunASR
            return FunASR()
        elif provider == "glm":
            from .implementations.glm_asr import GLMASR
            return GLMASR(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "glm-asr-2512"),
                stream=kwargs.get("stream", False)
            )
        elif provider == "faster_whisper":
            from .implementations.faster_whisper_asr import FasterWhisperASR
            return FasterWhisperASR(
                model=kwargs.get("model", "distil-large-v3"),
                language=kwargs.get("language", "zh"),
                device=kwargs.get("device", "auto"),
                compute_type=kwargs.get("compute_type", "default"),
                download_root=kwargs.get("download_root"),
                beam_size=kwargs.get("beam_size", 5),
                vad_filter=kwargs.get("vad_filter", True),
                vad_parameters=kwargs.get("vad_parameters", {})
            )
        elif provider == "mock":
            from .implementations.mock_asr import MockASR
            return MockASR()
        else:
            logger.warning(f"未知的 ASR 提供商: {provider}，使用 Mock 实现")
            from .implementations.mock_asr import MockASR
            return MockASR()
    
    @staticmethod
    def get_available_providers() -> List[str]:
        """获取所有可用的提供商列表"""
        return ["mock", "openai", "glm", "faster_whisper"]

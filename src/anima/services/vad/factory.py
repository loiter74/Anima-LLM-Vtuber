"""
VAD 工厂 - 根据配置创建 VAD 实例
"""

from typing import List
from loguru import logger

from .interface import VADInterface
from ...config.core.registry import ProviderRegistry


class VADFactory:
    """VAD 服务工厂类"""

    @staticmethod
    def create_from_config(config, **kwargs) -> VADInterface:
        """
        根据配置对象创建 VAD 实例（使用 ProviderRegistry）

        Args:
            config: VAD 配置对象
            **kwargs: 额外参数

        Returns:
            VADInterface: VAD 实例

        Raises:
            ValueError: 如果找不到对应的服务实现
        """
        try:
            vad = ProviderRegistry.create_service("vad", config)
            logger.info(f"VAD 服务创建成功: type={config.type}")
            return vad
        except Exception as e:
            logger.error(f"创建 VAD 服务失败 (type={config.type}): {type(e).__name__}: {e}")
            # 降级到 Mock 实现
            logger.warning(f"降级使用 MockVAD (原配置: {config.type})")
            from .implementations.mock_vad import MockVAD
            return MockVAD(
                sample_rate=getattr(config, 'sample_rate', 16000),
                db_threshold=-30.0,
                min_speech_duration=5,
                min_silence_duration=15,
            )

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
            try:
                from .implementations.silero_vad import SileroVAD
                return SileroVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                    prob_threshold=kwargs.get("prob_threshold", 0.4),
                    db_threshold=kwargs.get("db_threshold", 60),
                    required_hits=kwargs.get("required_hits", 3),
                    required_misses=kwargs.get("required_misses", 24),
                    smoothing_window=kwargs.get("smoothing_window", 5),
                )
            except ImportError as e:
                logger.warning(f"silero-vad 未安装，降级使用 Mock VAD: {e}")
                logger.info("提示: 运行 'pip install silero-vad' 安装 silero-vad")
                from .implementations.mock_vad import MockVAD
                return MockVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
                    db_threshold=kwargs.get("db_threshold", -30.0),
                    min_speech_duration=kwargs.get("min_speech_duration", 5),
                    min_silence_duration=kwargs.get("min_silence_duration", 15),
                )
            except Exception as e:
                logger.error(f"初始化 Silero VAD 失败，降级使用 Mock VAD: {e}")
                from .implementations.mock_vad import MockVAD
                return MockVAD(
                    sample_rate=kwargs.get("sample_rate", 16000),
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
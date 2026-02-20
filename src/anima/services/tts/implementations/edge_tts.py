"""
Edge TTS 实现 - 使用微软 Edge 浏览器的免费语音合成
"""

from typing import Union, Optional
from pathlib import Path
import tempfile
import asyncio

from loguru import logger

from ..interface import TTSInterface
from ....config.core.registry import ProviderRegistry
from ....config.providers.tts.edge import EdgeTTSConfig


@ProviderRegistry.register_service("tts", "edge")
class EdgeTTS(TTSInterface):
    """
    Edge TTS 实现
    使用微软 Edge 浏览器的免费语音合成服务
    无需 API Key，完全免费
    """

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
    ):
        """
        初始化 Edge TTS

        Args:
            voice: 音色，默认为中文女声
                   中文: zh-CN-XiaoxiaoNeural (女), zh-CN-YunxiNeural (男)
                   英文: en-US-JennyNeural (女), en-US-GuyNeural (男)
        """
        self.voice = voice
        self._communicate = None

    def _get_communicate(self):
        """懒加载 edge-tts 的 communicate 方法"""
        if self._communicate is None:
            try:
                import edge_tts
                self._communicate = edge_tts.Communicate
                logger.info("Edge TTS 客户端初始化成功")
            except ImportError as e:
                logger.error("未安装 edge-tts，请运行: pip install edge-tts")
                raise ImportError(
                    "edge-tts 未安装，请运行: pip install edge-tts"
                ) from e
        return self._communicate

    async def synthesize(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        voice: Optional[str] = None,
        **kwargs
    ) -> Union[bytes, str]:
        """
        将文本合成为语音

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选）
            voice: 音色（可选，覆盖默认值）
            **kwargs: 额外参数（忽略）

        Returns:
            Union[bytes, str]: 如果指定了 output_path，返回文件路径字符串
                               否则返回音频字节数据
        """
        import edge_tts

        # 使用传入的音色或默认音色
        actual_voice = voice or self.voice

        # 如果没有指定输出路径，创建临时文件
        if output_path is None:
            output_path = tempfile.mktemp(suffix=".mp3")
        else:
            output_path = Path(output_path)

        try:
            # 创建 communicate 实例并保存到文件
            communicate_instance = edge_tts.Communicate(text, actual_voice)

            # 使用 stream 方法获取音频数据并保存
            with open(output_path, "wb") as f:
                async for chunk in communicate_instance.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

            logger.debug(f"Edge TTS 合成完成: {len(text)} 字符 -> {output_path}")

            # 读取音频数据
            with open(output_path, 'rb') as f:
                audio_data = f.read()

            return audio_data if kwargs.get('return_bytes', False) else str(output_path)

        except Exception as e:
            logger.error(f"Edge TTS 合成失败: {e}")
            raise

    async def close(self) -> None:
        """清理资源（Edge TTS 不需要清理）"""
        self._communicate = None
        logger.debug("Edge TTS 资源已释放")

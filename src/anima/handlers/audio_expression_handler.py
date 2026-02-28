"""
音频 + 表情统一处理器
处理音频和表情时间轴，发送统一的 WebSocket 消息
"""

import base64
from pathlib import Path
from typing import TYPE_CHECKING
from loguru import logger

from .base_handler import BaseHandler
from anima.live2d.audio_analyzer import AudioAnalyzer
from anima.live2d.emotion_timeline import EmotionTimelineCalculator

if TYPE_CHECKING:
    from anima.core import OutputEvent


class AudioExpressionHandler(BaseHandler):
    """
    音频 + 表情统一处理器

    处理 AUDIO_WITH_EXPRESSION 事件，发送包含以下数据的统一消息：
    - 音频数据（base64 编码）
    - 音量包络（用于口型同步）
    - 表情时间轴（用于表情切换）
    - 文本内容

    替代分离的 AudioHandler 和 ExpressionHandler
    """

    def __init__(self, websocket_send=None, sample_rate: int = 50):
        """
        初始化处理器

        Args:
            websocket_send: WebSocket 发送函数
            sample_rate: 音量包络采样率（Hz）
        """
        super().__init__(websocket_send)
        self.audio_analyzer = AudioAnalyzer(sample_rate=sample_rate)
        self.timeline_calculator = EmotionTimelineCalculator(default_emotion="neutral")

    async def handle(self, event: "OutputEvent") -> None:
        """
        处理音频 + 表情事件

        Args:
            event: OutputEvent，data 应包含:
                - audio_path: 音频文件路径
                - emotions: 表情标签列表
                - text: 清理后的文本
                - seq: 序号
        """
        data = event.data
        audio_path = data.get("audio_path")
        emotions = data.get("emotions", [])
        text = data.get("text", "")
        seq = event.metadata.get("seq", event.seq)

        if not audio_path:
            logger.warning(f"[{self.name}] 缺少 audio_path")
            return

        try:
            # 1. 读取音频文件
            audio_base64 = self._read_audio_as_base64(audio_path)
            audio_format = Path(audio_path).suffix.lstrip('.')

            # 2. 计算音量包络
            volumes = self.audio_analyzer.compute_volume_envelope(audio_path)

            # 3. 获取音频时长
            duration = self.audio_analyzer.get_audio_duration(audio_path)

            # 4. 计算表情时间轴
            timeline = self.timeline_calculator.calculate(
                emotions=emotions,
                cleaned_text=text,
                audio_duration=duration
            )

            # 5. 构建表情时间轴数据（包含 intensity）
            expressions_data = {
                "segments": [
                    {
                        "emotion": seg.emotion,
                        "time": seg.start_time,
                        "duration": seg.duration,
                        "intensity": getattr(seg, 'intensity', 1.0)  # 强度值，默认 1.0
                    }
                    for seg in timeline.segments
                ],
                "total_duration": timeline.total_duration
            }

            # 6. 发送统一消息
            await self.send({
                "type": "audio_with_expression",
                "audio_data": audio_base64,
                "format": audio_format,
                "volumes": volumes,
                "expressions": expressions_data,
                "text": text,
                "seq": seq
            })

            logger.info(
                f"[{self.name}] 发送音频 + 表情: {duration:.2f}s, "
                f"{len(volumes)} 音量采样, {len(timeline.segments)} 个表情片段"
            )

        except Exception as e:
            logger.error(f"[{self.name}] 处理失败: {e}")
            # 发送错误到前端
            await self.send({
                "type": "error",
                "message": f"音频处理失败: {str(e)}",
                "seq": seq
            })

    def _read_audio_as_base64(self, audio_path: str) -> str:
        """
        读取音频文件并转换为 base64

        Args:
            audio_path: 音频文件路径

        Returns:
            base64 编码的音频数据
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        with open(audio_path, 'rb') as f:
            audio_data = f.read()

        return base64.b64encode(audio_data).decode('utf-8')

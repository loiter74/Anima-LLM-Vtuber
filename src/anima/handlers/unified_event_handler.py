"""
统一事件处理器（增强版）

整合情绪分析、时间轴计算和音频处理。
使用新的 IEmotionAnalyzer 和 ITimelineStrategy 接口。
"""

import base64
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any
from loguru import logger

from .base_handler import BaseHandler
from anima.live2d.analyzers.base import IEmotionAnalyzer, EmotionData
from anima.live2d.strategies.base import ITimelineStrategy, TimelineSegment
from anima.live2d.audio_analyzer import AudioAnalyzer
from anima.live2d.factory import (
    create_emotion_analyzer,
    create_timeline_strategy
)

if TYPE_CHECKING:
    from anima.core import OutputEvent


class UnifiedEventHandler(BaseHandler):
    """
    统一事件处理器

    整合情绪分析、时间轴计算和音频处理功能。
    使用新的策略模式和工厂模式，支持灵活的组件配置。

    功能:
    - 自动从文本中提取情绪（使用 IEmotionAnalyzer）
    - 计算情绪时间轴（使用 ITimelineStrategy）
    - 处理音频并计算音量包络
    - 发送统一的 WebSocket 消息

    Attributes:
        analyzer: 情绪分析器（LLMTagAnalyzer 或 KeywordAnalyzer）
        strategy: 时间轴策略（PositionBasedStrategy 等）
        audio_analyzer: 音频分析器
        sample_rate: 音量包络采样率

    Example:
        >>> handler = UnifiedEventHandler(
        ...     analyzer_type="llm_tag_analyzer",
        ...     strategy_type="duration_based"
        ... )
        >>> await handler.handle(event)
    """

    def __init__(
        self,
        websocket_send=None,
        analyzer_type: str = "llm_tag_analyzer",
        analyzer_config: Optional[Dict[str, Any]] = None,
        strategy_type: str = "position_based",
        strategy_config: Optional[Dict[str, Any]] = None,
        sample_rate: int = 50
    ):
        """
        初始化处理器

        Args:
            websocket_send: WebSocket 发送函数
            analyzer_type: 情绪分析器类型（"llm_tag_analyzer" 或 "keyword_analyzer"）
            analyzer_config: 情绪分析器配置
            strategy_type: 时间轴策略类型（"position_based", "duration_based", "intensity_based"）
            strategy_config: 时间轴策略配置
            sample_rate: 音量包络采样率（Hz）
        """
        super().__init__(websocket_send)

        # 创建情绪分析器
        try:
            self.analyzer = create_emotion_analyzer(
                analyzer_type,
                config=analyzer_config or {}
            )
            logger.info(f"[{self.name}] 使用情绪分析器: {self.analyzer.name}")
        except Exception as e:
            logger.error(f"[{self.name}] 创建情绪分析器失败: {e}")
            raise

        # 创建时间轴策略
        try:
            self.strategy = create_timeline_strategy(
                strategy_type,
                config=strategy_config or {}
            )
            logger.info(f"[{self.name}] 使用时间轴策略: {self.strategy.name}")
        except Exception as e:
            logger.error(f"[{self.name}] 创建时间轴策略失败: {e}")
            raise

        # 创建音频分析器
        self.audio_analyzer = AudioAnalyzer(sample_rate=sample_rate)
        self._sample_rate = sample_rate

    async def handle(self, event: "OutputEvent") -> None:
        """
        处理音频 + 表情事件

        Args:
            event: OutputEvent，data 应包含:
                - audio_path: 音频文件路径
                - text: 文本内容（可选，如果没有则从情绪分析器推断）
                - emotions: 情绪列表（可选，如果没有则从文本提取）
                - seq: 序号
        """
        data = event.data
        audio_path = data.get("audio_path")
        text = data.get("text", "")
        provided_emotions = data.get("emotions")
        seq = event.metadata.get("seq", event.seq)

        # 记录开始时间
        start_time = time.time()

        logger.info(
            f"[{self.name}] 开始处理 audio_with_expression 事件 (seq: {seq})"
        )

        if not audio_path:
            logger.warning(f"[{self.name}] 缺少 audio_path")
            return

        try:
            # 1. 读取音频文件
            audio_base64 = self._read_audio_as_base64(audio_path)
            audio_format = Path(audio_path).suffix.lstrip('.')

            logger.debug(f"[{self.name}] 音频读取完成 (格式: {audio_format})")

            # 2. 获取音频时长
            duration = self.audio_analyzer.get_audio_duration(audio_path)
            logger.debug(f"[{self.name}] 音频时长: {duration:.2f}s")

            # 3. 提取或使用提供的情绪
            extract_start = time.time()
            if provided_emotions:
                # 使用提供的情绪列表
                emotions = provided_emotions
                logger.debug(f"[{self.name}] 使用提供的情绪: {emotions}")
            else:
                # 从文本提取情绪
                emotion_data = self.analyzer.extract(text)
                emotions = self._extract_emotion_list(emotion_data)
                logger.debug(
                    f"[{self.name}] 情绪提取完成: {emotions} "
                    f"(分析器: {self.analyzer.name}, "
                    f"置信度: {emotion_data.confidence:.2f}, "
                    f"耗时: {(time.time() - extract_start)*1000:.1f}ms)"
                )

            # 4. 计算表情时间轴
            timeline_start = time.time()
            timeline_segments = self.strategy.calculate(
                emotions=emotions,
                text=text,
                audio_duration=duration
            )
            logger.debug(
                f"[{self.name}] 时间轴计算完成: {len(timeline_segments)} 个片段 "
                f"(策略: {self.strategy.name}, "
                f"耗时: {(time.time() - timeline_start)*1000:.1f}ms)"
            )

            # 5. 计算音量包络
            volume_start = time.time()
            volumes = self.audio_analyzer.compute_volume_envelope(audio_path)
            logger.debug(
                f"[{self.name}] 音量计算完成: {len(volumes)} 个采样 "
                f"(耗时: {(time.time() - volume_start)*1000:.1f}ms)"
            )

            # 6. 构建表情时间轴数据（包含 intensity）
            expressions_data = {
                "segments": [
                    {
                        "emotion": seg.emotion,
                        "time": seg.start_time,
                        "duration": seg.duration,
                        "intensity": getattr(seg, 'intensity', 1.0)  # ← 强度值
                    }
                    for seg in timeline_segments
                ],
                "total_duration": duration
            }

            # 7. 发送统一消息
            await self.send({
                "type": "audio_with_expression",
                "audio_data": audio_base64,
                "format": audio_format,
                "volumes": volumes,
                "expressions": expressions_data,
                "text": text,
                "seq": seq
            })

            total_time = time.time() - start_time

            logger.info(
                f"[{self.name}] 事件处理成功 (seq: {seq}) "
                f"- 总耗时: {total_time*1000:.1f}ms, "
                f"音频: {duration:.2f}s, "
                f"片段: {len(timeline_segments)}"
            )

        except Exception as e:
            logger.error(
                f"[{self.name}] 处理失败 (seq: {seq}): {e}",
                exc_info=True
            )
            # 发送错误到前端
            await self.send({
                "type": "error",
                "message": f"音频处理失败: {str(e)}",
                "seq": seq
            })

    def _extract_emotion_list(self, emotion_data: EmotionData) -> list:
        """
        从 EmotionData 中提取情绪列表

        Args:
            emotion_data: 情绪数据

        Returns:
            List[str]: 情绪列表
        """
        # 如果有时间轴，从时间轴提取情绪
        if emotion_data.timeline:
            return [item["emotion"] for item in emotion_data.timeline]

        # 否则，返回只包含主要情绪的列表
        return [emotion_data.primary] if emotion_data.primary else ["neutral"]

    def _build_expressions_data(
        self,
        segments: list,
        total_duration: float
    ) -> Dict[str, Any]:
        """
        构建表情时间轴数据

        Args:
            segments: TimelineSegment 列表
            total_duration: 总时长

        Returns:
            Dict: 表情数据（包含 intensity）
        """
        return {
            "segments": [
                seg.to_frontend_format()  # 使用 TimelineSegment 的方法，包含 intensity
                for seg in segments
            ],
            "total_duration": total_duration
        }

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

    @property
    def name(self) -> str:
        """处理器名称"""
        return "unified_event_handler"

    def get_config_info(self) -> Dict[str, Any]:
        """
        获取处理器配置信息

        Returns:
            Dict: 配置信息
        """
        return {
            "analyzer": self.analyzer.name,
            "strategy": self.strategy.name,
            "sample_rate": self._sample_rate
        }

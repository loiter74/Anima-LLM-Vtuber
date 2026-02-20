"""
音频 Handler - 处理音频事件
"""

from typing import TYPE_CHECKING
from pathlib import Path
import base64
from loguru import logger

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from anima.core import OutputEvent


class AudioHandler(BaseHandler):
    """
    音频 Handler

    处理 audio 事件，读取音频文件并发送到前端
    """

    async def handle(self, event: "OutputEvent") -> None:
        """处理音频事件"""
        audio_path = event.data.get("path")

        if not audio_path:
            logger.warning(f"AudioHandler: 收到音频事件但没有路径")
            return

        try:
            # 读取音频文件
            audio_file = Path(audio_path)

            if not audio_file.exists():
                logger.error(f"AudioHandler: 音频文件不存在: {audio_path}")
                return

            with open(audio_file, "rb") as f:
                audio_data = f.read()

            # 编码为 base64
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            # 发送音频到前端
            await self.send({
                "type": "audio",
                "audio_data": audio_base64,
                "format": "mp3",
                "seq": event.seq,
            })

            logger.info(f"AudioHandler: 发送音频 [{event.seq}] {len(audio_data)} bytes")

        except Exception as e:
            logger.error(f"AudioHandler: 处理音频失败: {e}")
            raise

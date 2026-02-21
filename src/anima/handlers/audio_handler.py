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

            # ========== PHASE 1.4: BACKEND LOGGING ==========
            # Log audio file info for debugging
            file_size = len(audio_data)
            logger.info(f"AudioHandler: 读取音频文件: {audio_path}")
            logger.info(f"AudioHandler: 文件大小: {file_size} bytes")

            # Log first 16 bytes in hex for format verification
            first_16_bytes = audio_data[:16].hex() if len(audio_data) >= 16 else audio_data.hex()
            logger.debug(f"AudioHandler: 文件前16字节 (hex): {first_16_bytes}")

            # 编码为 base64
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            # ========== PHASE 1.4: BASE64 ENCODING LOGS ==========
            logger.debug(f"AudioHandler: base64 长度: {len(audio_base64)}")
            logger.debug(f"AudioHandler: base64 前50字符: {audio_base64[:50]}")
            logger.debug(f"AudioHandler: base64 后50字符: {audio_base64[-50:]}")

            # 发送音频到前端
            await self.send({
                "type": "audio",
                "audio_data": audio_base64,
                "format": "mp3",
                "seq": event.seq,
            })

            logger.info(f"AudioHandler: 发送音频 [{event.seq}] {file_size} bytes (base64: {len(audio_base64)} chars)")

        except Exception as e:
            logger.error(f"AudioHandler: 处理音频失败: {e}")
            raise

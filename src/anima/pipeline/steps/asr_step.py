"""
ASR 步骤 - 语音转文字
"""

import json
from typing import TYPE_CHECKING
from loguru import logger

from ..base import PipelineStep, PipelineStepError

if TYPE_CHECKING:
    from anima.core import PipelineContext, WebSocketSend
    from anima.services.asr import ASRInterface


class ASRStep(PipelineStep):
    """
    ASR 步骤
    
    如果输入是音频，调用 ASR 引擎转换为文字
    如果输入是文本，直接使用
    """
    
    def __init__(
        self,
        asr_engine: "ASRInterface",
        websocket_send: "WebSocketSend",
    ):
        self.asr_engine = asr_engine
        self.websocket_send = websocket_send
    
    async def process(self, ctx: "PipelineContext") -> None:
        """处理输入"""
        # 文本输入：直接使用
        if ctx.is_text_input():
            ctx.text = ctx.raw_input
            logger.debug(f"文本输入: {ctx.text[:50]}...")
            return
        
        # 音频输入：调用 ASR
        if ctx.is_audio_input():
            await self._process_audio(ctx)
            return
        
        # 未知类型
        ctx.set_error(self.name, f"未知的输入类型: {type(ctx.raw_input)}")
    
    async def _process_audio(self, ctx: "PipelineContext") -> None:
        """处理音频输入"""
        audio_data = ctx.raw_input
        
        # 检查音频是否为空
        if len(audio_data) == 0:
            ctx.text = ""
            ctx.set_error(self.name, "音频数据为空")
            return
        
        # 通知前端 ASR 开始
        await self._send_control("asr-start")
        
        try:
            # 检查 ASR 引擎
            if self.asr_engine is None:
                ctx.text = ""
                ctx.set_error(self.name, "ASR 引擎未初始化")
                return
            
            # 调用 ASR 识别
            logger.debug(f"ASR 处理中，音频长度: {len(audio_data)} 采样点")
            text = await self.asr_engine.transcribe(audio_data)
            
            # 更新上下文
            ctx.text = text
            logger.info(f"ASR 结果: {text}")
            
            # 发送转录结果到前端
            await self.websocket_send(json.dumps({
                "type": "user-transcript",
                "text": text
            }))
            
        except Exception as e:
            ctx.set_error(self.name, f"ASR 识别失败: {str(e)}")
            logger.error(f"ASR 识别出错: {e}")
            
            # 发送错误到前端
            await self.websocket_send(json.dumps({
                "type": "error",
                "message": f"语音识别失败: {str(e)}"
            }))
            
            raise PipelineStepError(self.name, str(e), e)
    
    async def _send_control(self, text: str) -> None:
        """发送控制信号到前端"""
        await self.websocket_send(json.dumps({
            "type": "control",
            "text": text
        }))
"""
文本清洗步骤
"""

import re
from typing import TYPE_CHECKING
from loguru import logger

from ..base import PipelineStep

if TYPE_CHECKING:
    from anima.core import PipelineContext


class TextCleanStep(PipelineStep):
    """
    文本清洗步骤
    
    清洗输入文本：
    - 去除多余空白
    - 去除特殊字符
    - 统一标点符号
    """
    
    def __init__(self, remove_emoji: bool = False):
        """
        初始化
        
        Args:
            remove_emoji: 是否移除 emoji
        """
        self.remove_emoji = remove_emoji
    
    async def process(self, ctx: "PipelineContext") -> None:
        """处理文本"""
        if not ctx.text:
            return
        
        text = ctx.text
        
        # 去除首尾空白
        text = text.strip()
        
        # 去除多余空白
        text = re.sub(r'\s+', ' ', text)
        
        # 可选：移除 emoji
        if self.remove_emoji:
            text = self._remove_emoji(text)
        
        # 更新上下文
        ctx.text = text
        
        logger.debug(f"文本清洗: '{ctx.raw_input[:30]}...' -> '{text[:30]}...'")
    
    def _remove_emoji(self, text: str) -> str:
        """移除 emoji"""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub('', text)
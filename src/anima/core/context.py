"""
管线上下文
在 Pipeline 中传递的上下文对象
"""

from dataclasses import dataclass, field
from typing import Any, Union, Optional, List, Dict
import numpy as np


@dataclass
class PipelineContext:
    """
    管线上下文
    
    在整个处理管线中传递的上下文对象
    每个 PipelineStep 可以读取和修改此上下文
    """
    # 原始输入（文本或音频数据）
    raw_input: Union[str, np.ndarray]
    
    # 处理后的文本（由 ASR 步骤填充，或直接使用原始文本）
    text: str = ""
    
    # 可选的图片列表
    images: Optional[List[Dict[str, Any]]] = None
    
    # 发送者名称
    from_name: str = "User"
    
    # 元数据（可包含 skip_history, proactive_speak 等标志）
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 错误信息（如果处理过程中出错）
    error: Optional[str] = None
    
    # Agent 响应（由 AgentStep 填充）
    response: str = ""
    
    # 是否应跳过后续处理
    skip_remaining: bool = False
    
    def is_audio_input(self) -> bool:
        """检查原始输入是否为音频"""
        return isinstance(self.raw_input, np.ndarray)
    
    def is_text_input(self) -> bool:
        """检查原始输入是否为文本"""
        return isinstance(self.raw_input, str)
    
    def should_skip_history(self) -> bool:
        """检查是否应跳过历史存储"""
        return self.metadata.get("skip_history", False)
    
    def should_skip_memory(self) -> bool:
        """检查是否应跳过 AI 内部记忆"""
        return self.metadata.get("skip_memory", False)
    
    def set_error(self, step_name: str, message: str) -> None:
        """设置错误信息"""
        self.error = f"[{step_name}] {message}"
    
    def skip(self) -> None:
        """跳过后续处理"""
        self.skip_remaining = True
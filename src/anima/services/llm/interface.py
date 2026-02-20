"""
LLM (大语言模型) 服务接口定义
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, List, Dict, Any


class LLMInterface(ABC):
    """
    LLM 服务接口的抽象基类
    所有 LLM 实现都必须继承此类并实现其抽象方法
    """

    @abstractmethod
    async def chat(
        self,
        user_input: str,
        **kwargs
    ) -> str:
        """
        与 Agent 进行对话

        Args:
            user_input: 用户输入
            **kwargs: 额外参数

        Returns:
            str: Agent 的回复
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        user_input: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """
        流式对话

        Args:
            user_input: 用户输入
            **kwargs: 额外参数

        Yields:
            str: Agent 回复的文本片段
        """
        pass

    @abstractmethod
    def set_system_prompt(self, prompt: str) -> None:
        """
        设置系统提示词

        Args:
            prompt: 系统提示词
        """
        pass

    @abstractmethod
    def get_history(self) -> List[Dict[str, Any]]:
        """
        获取对话历史

        Returns:
            List[Dict[str, Any]]: 对话历史列表
        """
        pass

    @abstractmethod
    def clear_history(self) -> None:
        """清空对话历史"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """清理资源"""
        pass
    
    @abstractmethod
    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        处理用户打断
        
        Args:
            heard_response: 用户听到的部分回复（可用于存储历史）
        """
        pass
    
    @abstractmethod
    def set_memory_from_history(
        self,
        conf_uid: str,
        history_uid: str
    ) -> None:
        """
        从历史记录恢复对话记忆

        Args:
            conf_uid: 配置 UID
            history_uid: 历史 UID
        """
        pass


# 别名：保持向后兼容
AgentInterface = LLMInterface

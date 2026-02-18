"""
Mock Agent 实现 - 用于测试和开发
"""

from typing import AsyncIterator, List, Dict, Any, TYPE_CHECKING

from ..interface import AgentInterface
from anima.config.core.registry import ProviderRegistry
from anima.config import MockLLMConfig

if TYPE_CHECKING:
    from anima.config.providers.llm.base import LLMBaseConfig


@ProviderRegistry.register_service("llm", "mock")
class MockAgent(AgentInterface):
    """
    Mock Agent 实现
    不调用实际的 LLM，返回固定的模拟回复
    
    特性:
    - 通过 @ProviderRegistry.register_service 注册
    - 支持 from_config 从配置创建实例
    """
    
    # 类级别属性：支持的配置类型
    config_class = MockLLMConfig

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        self.history: List[Dict[str, Any]] = []
        self.call_count = 0

    @classmethod
    def from_config(cls, config: "LLMBaseConfig", system_prompt: str = "", **kwargs) -> "MockAgent":
        """
        从配置对象创建实例
        
        Args:
            config: LLM 配置对象
            system_prompt: 系统提示词
            **kwargs: 额外参数（忽略）
        
        Returns:
            MockAgent 实例
        """
        # Mock 不需要配置中的任何字段
        return cls(system_prompt=system_prompt)

    async def chat(
        self,
        user_input: str,
        **kwargs
    ) -> str:
        """返回模拟的回复"""
        # 模拟处理延迟
        import asyncio
        await asyncio.sleep(0.1)
        
        # 记录到历史
        self.history.append({"role": "user", "content": user_input})
        
        # 生成模拟回复
        self.call_count += 1
        responses = [
            f"这是第 {self.call_count} 条模拟回复。你刚才说的是：「{user_input}」",
            f"收到你的消息：「{user_input}」。我是一个 Mock Agent，用于测试。",
            f"你好！你说的是：「{user_input}」。有什么我可以帮助你的吗？",
        ]
        response = responses[self.call_count % len(responses)]
        
        # 记录回复到历史
        self.history.append({"role": "assistant", "content": response})
        
        return response

    async def chat_stream(
        self,
        user_input: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """流式返回模拟回复"""
        response = await self.chat(user_input, **kwargs)
        
        # 模拟流式输出
        for char in response:
            yield char

    def set_system_prompt(self, prompt: str) -> None:
        """设置系统提示词"""
        self.system_prompt = prompt

    def get_history(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.history.copy()

    def clear_history(self) -> None:
        """清空对话历史"""
        self.history = []
        self.call_count = 0

    async def close(self) -> None:
        """无需清理资源"""
        pass
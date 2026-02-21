"""
Mock LLM 实现 - 用于测试和开发
"""

from typing import AsyncIterator, List, Dict, Any, TYPE_CHECKING
import time
import uuid
from loguru import logger

from ..interface import LLMInterface
from ....config.core.registry import ProviderRegistry
from ....config import MockLLMConfig

if TYPE_CHECKING:
    from anima.config.providers.llm.base import LLMBaseConfig


@ProviderRegistry.register_service("llm", "mock")
class MockLLM(LLMInterface):
    """
    Mock LLM 实现
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
        self.instance_id = str(uuid.uuid4())[:8]

    @classmethod
    def from_config(cls, config: "LLMBaseConfig", system_prompt: str = "", **kwargs) -> "MockLLM":
        """
        从配置对象创建实例

        Args:
            config: LLM 配置对象
            system_prompt: 系统提示词
            **kwargs: 额外参数（忽略）

        Returns:
            MockLLM 实例
        """
        # Mock 不需要配置中的任何字段
        instance = cls(system_prompt=system_prompt)
        logger.info(f"[MockLLM-{instance.instance_id}] 初始化完成")
        return instance

    async def chat(
        self,
        user_input: str,
        **kwargs
    ) -> str:
        """返回模拟的回复"""
        # 调用计数
        self.call_count += 1
        call_id = f"{self.instance_id}-{self.call_count}"

        # 记录调用开始
        start_time = time.time()
        input_length = len(user_input)
        history_length = len(self.history)

        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")
        logger.info(f"[MockLLM:{call_id}] 🔵 开始调用 (模拟模式)")
        logger.info(f"[MockLLM:{call_id}] 输入: {user_input[:100]}{'...' if input_length > 100 else ''} (长度: {input_length})")
        logger.info(f"[MockLLM:{call_id}] 历史轮数: {history_length // 2}")

        # 模拟处理延迟
        import asyncio
        await asyncio.sleep(0.1)

        # 记录到历史
        self.history.append({"role": "user", "content": user_input})

        # 生成模拟回复
        responses = [
            f"这是第 {self.call_count} 条模拟回复。你刚才说的是：「{user_input}」",
            f"收到你的消息：「{user_input}」。我是一个 Mock LLM，用于测试和开发。",
            f"你好！你说的是：「{user_input}」。有什么我可以帮助你的吗？",
        ]
        response = responses[self.call_count % len(responses)]

        # 记录回复到历史
        self.history.append({"role": "assistant", "content": response})

        # 计算耗时
        elapsed_time = time.time() - start_time
        output_length = len(response)

        logger.info(f"[MockLLM:{call_id}] 🟢 调用成功")
        logger.info(f"[MockLLM:{call_id}] 耗时: {elapsed_time:.2f}秒")
        logger.info(f"[MockLLM:{call_id}] 输出: {response[:100]}{'...' if output_length > 100 else ''} (长度: {output_length})")
        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")

        return response

    async def chat_stream(
        self,
        user_input: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """流式返回模拟回复"""
        # 调用计数
        self.call_count += 1
        call_id = f"{self.instance_id}-{self.call_count}"

        # 记录调用开始
        start_time = time.time()
        input_length = len(user_input)

        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")
        logger.info(f"[MockLLM:{call_id}] 🔵 开始流式调用 (模拟模式)")
        logger.info(f"[MockLLM:{call_id}] 输入: {user_input[:100]}{'...' if input_length > 100 else ''}")

        response = await self.chat(user_input, **kwargs)

        # 模拟流式输出
        chunk_count = 0
        for char in response:
            chunk_count += 1
            yield char

        # 计算耗时
        elapsed_time = time.time() - start_time

        logger.info(f"[MockLLM:{call_id}] 🟢 流式调用成功")
        logger.info(f"[MockLLM:{call_id}] 耗时: {elapsed_time:.2f}秒")
        logger.info(f"[MockLLM:{call_id}] 分块数: {chunk_count}")
        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")

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
    
    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        处理用户打断
        
        Args:
            heard_response: 用户听到的部分回复
        """
        if heard_response:
            # 保存部分回复到历史
            if self.history and self.history[-1].get("role") == "user":
                self.history.append({
                    "role": "assistant",
                    "content": heard_response
                })
                self.history.append({
                    "role": "system",
                    "content": "[用户打断了对话]"
                })
    
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
        # Mock 实现：不做任何操作
        pass

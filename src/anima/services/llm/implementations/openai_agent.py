"""
OpenAI Agent 实现
使用 openai SDK 调用 OpenAI GPT 模型
"""

from typing import AsyncIterator, List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from openai import AsyncOpenAI

from ..interface import AgentInterface
from ....config.core.registry import ProviderRegistry
from ....config import OpenAILLMConfig

if TYPE_CHECKING:
    from anima.config.providers.llm.base import LLMBaseConfig


@ProviderRegistry.register_service("llm", "openai")
class OpenAIAgent(AgentInterface):
    """
    OpenAI GPT 模型 Agent 实现
    
    使用官方 openai SDK 调用 GPT-4、GPT-3.5 等模型
    支持流式输出和自定义 base_url（兼容其他 OpenAI API 兼容服务）
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        system_prompt: str = "",
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ):
        """
        初始化 OpenAI Agent
        
        Args:
            api_key: OpenAI API Key
            model: 模型名称 (gpt-4, gpt-4o, gpt-3.5-turbo 等)
            system_prompt: 系统提示词
            base_url: 自定义 API 端点（可选）
            temperature: 温度参数
            max_tokens: 最大生成 token 数
        """
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # 对话历史
        self.history: List[Dict[str, str]] = []
        
        # 初始化异步客户端
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        
        self.client = AsyncOpenAI(**client_kwargs)
        
        logger.info(f"OpenAIAgent 初始化完成: model={model}, base_url={base_url or 'default'}")

    @classmethod
    def from_config(cls, config: "LLMBaseConfig", system_prompt: str = "", **kwargs) -> "OpenAIAgent":
        """
        从配置对象创建实例
        
        Args:
            config: OpenAILLMConfig 配置对象
            system_prompt: 系统提示词
            **kwargs: 额外参数（忽略）
        
        Returns:
            OpenAIAgent 实例
        
        Raises:
            TypeError: 如果配置类型不匹配
        """
        if not isinstance(config, OpenAILLMConfig):
            raise TypeError(f"OpenAIAgent 需要 OpenAILLMConfig，收到: {type(config)}")
        
        return cls(
            api_key=config.api_key,
            model=config.model,
            system_prompt=system_prompt,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens
        )

    def _build_messages(self, user_input: str) -> List[Dict[str, str]]:
        """
        构建消息列表
        
        Args:
            user_input: 用户输入
            
        Returns:
            List[Dict[str, str]]: 完整的消息列表
        """
        messages = []
        
        # 添加系统提示词
        if self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt
            })
        
        # 添加历史对话
        messages.extend(self.history)
        
        # 添加当前用户输入
        messages.append({
            "role": "user",
            "content": user_input
        })
        
        return messages

    async def chat(self, user_input: str, **kwargs) -> str:
        """
        与 OpenAI 模型进行对话
        
        Args:
            user_input: 用户输入
            **kwargs: 额外参数
            
        Returns:
            str: 模型回复
        """
        messages = self._build_messages(user_input)
        
        try:
            response = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            
            assistant_message = response.choices[0].message.content
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": assistant_message})
            
            logger.debug(f"OpenAI 回复: {assistant_message[:100]}...")
            return assistant_message
            
        except Exception as e:
            logger.error(f"OpenAI 对话异常: {e}")
            raise

    async def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        """
        流式对话
        
        Args:
            user_input: 用户输入
            **kwargs: 额外参数
            
        Yields:
            str: 模型回复的文本片段
        """
        messages = self._build_messages(user_input)
        
        full_response = ""
        
        try:
            response = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=True
            )
            
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            logger.error(f"OpenAI 流式对话异常: {e}")
            raise

    def set_system_prompt(self, prompt: str) -> None:
        """设置系统提示词"""
        self.system_prompt = prompt
        logger.debug(f"系统提示词已更新: {prompt[:50]}...")

    def get_history(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.history.copy()

    def clear_history(self) -> None:
        """清空对话历史"""
        self.history.clear()
        logger.debug("对话历史已清空")

    async def close(self) -> None:
        """清理资源"""
        await self.client.close()
        logger.info("OpenAIAgent 资源已释放")
    
    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        处理用户打断
        
        Args:
            heard_response: 用户听到的部分回复
        """
        if heard_response:
            # 保存部分回复到历史
            if self.history and self.history[-1].get("role") == "user":
                # 获取最后一个用户输入
                last_user_input = self.history[-1].get("content", "")
                # 添加部分 AI 回复
                self.history.append({
                    "role": "assistant",
                    "content": heard_response
                })
                # 添加打断标记
                self.history.append({
                    "role": "system",
                    "content": "[用户打断了对话]"
                })
        
        logger.info(f"对话被打断，已保存部分回复: {heard_response[:50] if heard_response else '(空)'}...")
    
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
        # TODO: 实现从持久化存储加载历史
        # 这里暂时只记录日志
        logger.info(f"尝试从历史恢复记忆: conf_uid={conf_uid}, history_uid={history_uid}")

"""
GLM (智谱AI) Agent 实现
使用 zai-sdk 调用智谱 AI 的 GLM 模型
"""

from typing import AsyncIterator, List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from zai import ZhipuAiClient

from ..interface import AgentInterface
from anima.config.core.registry import ProviderRegistry
from anima.config import GLMLLMConfig

if TYPE_CHECKING:
    from anima.config.providers.llm.base import LLMBaseConfig


@ProviderRegistry.register_service("llm", "glm")
class GLMAgent(AgentInterface):
    """
    智谱 AI GLM 模型 Agent 实现
    
    使用 zai-sdk 调用 GLM-4、GLM-5 等模型
    支持深度思考模式和流式输出
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "glm-4-flash",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        **kwargs
    ):
        """
        初始化 GLM Agent
        
        Args:
            api_key: 智谱 AI API Key
            model: 模型名称 (glm-4, glm-4-flash, glm-5 等)
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            enable_thinking: 是否启用深度思考模式
        """
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        
        # 对话历史
        self.history: List[Dict[str, str]] = []
        
        # 初始化客户端
        self.client = ZhipuAiClient(api_key=api_key)
        
        logger.info(f"GLMAgent 初始化完成: model={model}, thinking={enable_thinking}")

    @classmethod
    def from_config(cls, config: "LLMBaseConfig", system_prompt: str = "", **kwargs) -> "GLMAgent":
        """
        从配置对象创建实例
        
        Args:
            config: GLMLLMConfig 配置对象
            system_prompt: 系统提示词
            **kwargs: 额外参数（忽略）
        
        Returns:
            GLMAgent 实例
        
        Raises:
            TypeError: 如果配置类型不匹配
        """
        if not isinstance(config, GLMLLMConfig):
            raise TypeError(f"GLMAgent 需要 GLMLLMConfig，收到: {type(config)}")
        
        return cls(
            api_key=config.api_key,
            model=config.model,
            system_prompt=system_prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            enable_thinking=config.enable_thinking
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
        与 GLM 模型进行对话
        
        Args:
            user_input: 用户输入
            **kwargs: 额外参数
            
        Returns:
            str: 模型回复
        """
        messages = self._build_messages(user_input)
        
        # 构建请求参数
        request_params = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }
        
        # 启用深度思考模式
        if self.enable_thinking:
            request_params["thinking"] = {"type": "enabled"}
        
        try:
            # zai-sdk 是同步的，需要在异步环境中运行
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(**request_params)
            )
            
            assistant_message = response.choices[0].message.content
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": assistant_message})
            
            logger.debug(f"GLM 回复: {assistant_message[:100]}...")
            return assistant_message
            
        except Exception as e:
            logger.error(f"GLM 对话异常: {e}")
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
        
        # 构建请求参数
        request_params = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True
        }
        
        # 启用深度思考模式
        if self.enable_thinking:
            request_params["thinking"] = {"type": "enabled"}
        
        full_response = ""
        
        try:
            # 在线程池中运行同步流式调用
            import asyncio
            loop = asyncio.get_event_loop()
            
            def sync_stream():
                return self.client.chat.completions.create(**request_params)
            
            response = await loop.run_in_executor(None, sync_stream)
            
            for chunk in response:
                # 处理思考内容
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content:
                    reasoning = chunk.choices[0].delta.reasoning_content
                    full_response += reasoning
                    yield reasoning
                
                # 处理正式回复
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            logger.error(f"GLM 流式对话异常: {e}")
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
        # zai-sdk 的客户端不需要显式关闭
        logger.info("GLMAgent 资源已释放")
"""
Ollama LLM 实现
使用 ollama SDK 调用本地 Ollama 模型
"""

from typing import AsyncIterator, List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
import ollama

from ..interface import LLMInterface
from anima.config.core.registry import ProviderRegistry
from anima.config import OllamaLLMConfig

if TYPE_CHECKING:
    from anima.config.providers.llm.base import LLMBaseConfig


@ProviderRegistry.register_service("llm", "ollama")
class OllamaLLM(LLMInterface):
    """
    Ollama 本地模型 Agent 实现
    
    使用 ollama SDK 调用本地运行的 LLaMA、Mistral 等模型
    支持流式输出
    """
    
    def __init__(
        self,
        model: str = "llama3",
        system_prompt: str = "",
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        初始化 Ollama LLM
        
        Args:
            model: 模型名称 (llama3, mistral, qwen 等)
            system_prompt: 系统提示词
            base_url: Ollama 服务地址（默认 http://localhost:11434）
            temperature: 温度参数
            max_tokens: 最大生成 token 数
        """
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url or "http://localhost:11434"
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # 对话历史
        self.history: List[Dict[str, str]] = []
        
        # 初始化客户端
        client_kwargs = {"host": self.base_url}
        self.client = ollama.Client(**client_kwargs)
        
        logger.info(f"OllamaLLM 初始化完成: model={model}, base_url={self.base_url}")

    @classmethod
    def from_config(cls, config: "LLMBaseConfig", system_prompt: str = "", **kwargs) -> "OllamaLLM":
        """
        从配置对象创建实例
        
        Args:
            config: OllamaLLMConfig 配置对象
            system_prompt: 系统提示词
            **kwargs: 额外参数（忽略）
        
        Returns:
            OllamaLLM 实例
        
        Raises:
            TypeError: 如果配置类型不匹配
        """
        if not isinstance(config, OllamaLLMConfig):
            raise TypeError(f"OllamaLLM 需要 OllamaLLMConfig，收到: {type(config)}")
        
        return cls(
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
        与 Ollama 模型进行对话
        
        Args:
            user_input: 用户输入
            **kwargs: 额外参数
            
        Returns:
            str: 模型回复
        """
        messages = self._build_messages(user_input)
        
        try:
            # ollama SDK 是同步的，需要在线程池中运行
            import asyncio
            loop = asyncio.get_event_loop()
            
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    options={
                        "temperature": kwargs.get("temperature", self.temperature),
                        "num_predict": kwargs.get("max_tokens", self.max_tokens)
                    }
                )
            )
            
            assistant_message = response["message"]["content"]
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": assistant_message})
            
            logger.debug(f"Ollama 回复: {assistant_message[:100]}...")
            return assistant_message
            
        except Exception as e:
            logger.error(f"Ollama 对话异常: {e}")
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
            import asyncio
            loop = asyncio.get_event_loop()
            
            # 在线程池中运行同步流式调用
            def sync_stream():
                return self.client.chat(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    stream=True,
                    options={
                        "temperature": kwargs.get("temperature", self.temperature),
                        "num_predict": kwargs.get("max_tokens", self.max_tokens)
                    }
                )
            
            stream = await loop.run_in_executor(None, sync_stream)
            
            for chunk in stream:
                if "message" in chunk and "content" in chunk["message"]:
                    content = chunk["message"]["content"]
                    full_response += content
                    yield content
            
            # 更新历史
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            logger.error(f"Ollama 流式对话异常: {e}")
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
        # Ollama 客户端不需要显式关闭
        logger.info("OllamaLLM 资源已释放")
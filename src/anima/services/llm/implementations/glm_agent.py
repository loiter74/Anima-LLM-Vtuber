"""
GLM (智谱AI) Agent 实现
使用 zai-sdk 调用智谱 AI 的 GLM 模型
"""

from typing import AsyncIterator, List, Dict, Any, Optional, TYPE_CHECKING
from loguru import logger
from zai import ZhipuAiClient
import asyncio
import time

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
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 60,
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
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

        # 验证 API Key
        if not api_key or api_key.strip() == "" or api_key == "${LLM_API_KEY}":
            raise ValueError(
                "GLM API Key 未设置！请设置环境变量 LLM_API_KEY "
                "或在配置文件中提供有效的 api_key"
            )

        # 对话历史
        self.history: List[Dict[str, str]] = []

        # 初始化客户端
        try:
            self.client = ZhipuAiClient(api_key=api_key)
            logger.info(f"GLMAgent 初始化完成: model={model}, thinking={enable_thinking}")
        except Exception as e:
            logger.error(f"GLM 客户端初始化失败: {e}")
            raise

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
            enable_thinking=config.enable_thinking,
            max_retries=getattr(config, 'max_retries', 3),
            retry_delay=getattr(config, 'retry_delay', 1.0),
            timeout=getattr(config, 'timeout', 60),
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
            "timeout": kwargs.get("timeout", self.timeout),
        }

        # 启用深度思考模式
        if self.enable_thinking:
            request_params["thinking"] = {"type": "enabled"}

        last_error = None

        # 重试机制
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"GLM 请求尝试 {attempt + 1}/{self.max_retries}")

                # zai-sdk 是同步的，需要在异步环境中运行
                loop = asyncio.get_event_loop()

                # 使用 asyncio.wait_for 添加超时
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.client.chat.completions.create(**request_params)
                    ),
                    timeout=self.timeout
                )

                assistant_message = response.choices[0].message.content

                # 更新历史
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": assistant_message})

                logger.debug(f"GLM 回复: {assistant_message[:100]}...")
                return assistant_message

            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {self.timeout} 秒）"
                logger.warning(f"GLM 请求超时，尝试 {attempt + 1}/{self.max_retries}")

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)

                # 详细错误分类
                if "Connection" in error_msg or "connection" in error_msg:
                    last_error = f"网络连接错误: {error_msg}"
                    logger.warning(f"GLM 连接错误，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")
                elif "401" in error_msg or "Unauthorized" in error_msg:
                    last_error = "API Key 无效或未授权，请检查 LLM_API_KEY 环境变量"
                    logger.error(f"GLM API Key 错误: {error_msg}")
                    raise ValueError(last_error) from e
                elif "429" in error_msg:
                    last_error = f"API 请求频率超限: {error_msg}"
                    logger.warning(f"GLM 频率限制，尝试 {attempt + 1}/{self.max_retries}")
                elif "500" in error_msg or "502" in error_msg or "503" in error_msg:
                    last_error = f"GLM 服务器错误: {error_msg}"
                    logger.warning(f"GLM 服务器错误，尝试 {attempt + 1}/{self.max_retries}")
                else:
                    last_error = f"{error_type}: {error_msg}"
                    logger.warning(f"GLM 请求失败，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")

            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)  # 递增延迟
                logger.debug(f"等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)

        # 所有重试都失败
        error_msg = f"GLM 对话失败，已重试 {self.max_retries} 次。最后错误: {last_error}"
        logger.error(error_msg)
        raise ConnectionError(error_msg)

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
            "stream": True,
            "timeout": kwargs.get("timeout", self.timeout),
        }

        # 启用深度思考模式
        if self.enable_thinking:
            request_params["thinking"] = {"type": "enabled"}

        full_response = ""
        last_error = None

        # 重试机制
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"GLM 流式请求尝试 {attempt + 1}/{self.max_retries}")

                # 在线程池中运行同步流式调用，带超时
                loop = asyncio.get_event_loop()

                def sync_stream():
                    return self.client.chat.completions.create(**request_params)

                # 使用 asyncio.wait_for 添加超时
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, sync_stream),
                    timeout=self.timeout
                )

                # 处理流式响应
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

                # 成功完成，更新历史
                self.history.append({"role": "user", "content": user_input})
                self.history.append({"role": "assistant", "content": full_response})

                logger.debug(f"GLM 流式响应成功，总长度: {len(full_response)}")
                return

            except asyncio.TimeoutError:
                last_error = f"请求超时（超过 {self.timeout} 秒）"
                logger.warning(f"GLM 流式请求超时，尝试 {attempt + 1}/{self.max_retries}")

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)

                # 详细错误分类
                if "Connection" in error_msg or "connection" in error_msg:
                    last_error = f"网络连接错误: {error_msg}"
                    logger.warning(f"GLM 连接错误，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")
                elif "401" in error_msg or "Unauthorized" in error_msg:
                    last_error = "API Key 无效或未授权，请检查 LLM_API_KEY 环境变量"
                    logger.error(f"GLM API Key 错误: {error_msg}")
                    # 认证错误不需要重试
                    raise ValueError(last_error) from e
                elif "429" in error_msg:
                    last_error = f"API 请求频率超限: {error_msg}"
                    logger.warning(f"GLM 频率限制，尝试 {attempt + 1}/{self.max_retries}")
                elif "500" in error_msg or "502" in error_msg or "503" in error_msg:
                    last_error = f"GLM 服务器错误: {error_msg}"
                    logger.warning(f"GLM 服务器错误，尝试 {attempt + 1}/{self.max_retries}")
                else:
                    last_error = f"{error_type}: {error_msg}"
                    logger.warning(f"GLM 请求失败，尝试 {attempt + 1}/{self.max_retries}: {error_msg}")

            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries - 1:
                wait_time = self.retry_delay * (attempt + 1)  # 递增延迟
                logger.debug(f"等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)

        # 所有重试都失败
        error_msg = f"GLM 流式对话失败，已重试 {self.max_retries} 次。最后错误: {last_error}"
        logger.error(error_msg)
        raise ConnectionError(error_msg)

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
            logger.info(f"GLMAgent 处理打断，已保存部分回复: {heard_response[:50]}...")
        else:
            logger.info("GLMAgent 收到打断信号")

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
        # TODO: 实现从文件/数据库加载历史记录
        logger.debug(f"set_memory_from_history: conf_uid={conf_uid}, history_uid={history_uid}")
        pass

    async def close(self) -> None:
        """清理资源"""
        # zai-sdk 的客户端不需要显式关闭
        logger.info("GLMAgent 资源已释放")
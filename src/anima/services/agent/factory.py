"""
Agent 工厂 - 根据 LLM 配置自动创建 Agent 实例
"""

from loguru import logger

from .interface import AgentInterface
from anima.config.core.registry import ProviderRegistry
from anima.config import LLMConfig


class AgentFactory:
    """
    Agent 服务工厂类（简化版）
    
    使用 ProviderRegistry 自动查找并实例化服务，
    无需手动维护 if-elif 链。
    
    新增提供者只需：
    1. 创建配置类并注册
    2. 创建服务类并注册
    工厂代码无需任何修改。
    """
    
    @staticmethod
    def create_from_config(config: LLMConfig, system_prompt: str = "") -> AgentInterface:
        """
        根据配置对象自动创建 Agent 实例
        
        Args:
            config: LLM 配置对象 (Discriminated Union)
            system_prompt: 系统提示词
            
        Returns:
            AgentInterface: Agent 实例
        
        Raises:
            ValueError: 如果找不到对应的服务实现
        """
        try:
            # 使用 Registry 自动查找并实例化
            agent = ProviderRegistry.create_service("llm", config, system_prompt=system_prompt)
            logger.info(f"Agent 创建成功: type={config.type}")
            return agent
        except ValueError as e:
            logger.error(f"创建 Agent 失败: {e}")
            # 降级到 Mock 实现
            logger.warning("降级使用 MockAgent")
            from .implementations.mock_agent import MockAgent
            return MockAgent(system_prompt=system_prompt)

    @staticmethod
    def create(provider: str, system_prompt: str = "", **kwargs) -> AgentInterface:
        """
        根据提供商名称创建 Agent 实例（向后兼容）
        
        Args:
            provider: 提供商名称
            system_prompt: 系统提示词
            **kwargs: 传递给具体实现的参数
            
        Returns:
            AgentInterface: Agent 实例
        """
        from anima.config import (
            MockLLMConfig,
            OpenAILLMConfig,
            GLMLLMConfig,
            OllamaLLMConfig,
        )
        
        # 根据提供商名称构建配置对象
        config_map = {
            "openai": lambda: OpenAILLMConfig(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "gpt-4o-mini"),
                base_url=kwargs.get("base_url"),
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 1000)
            ),
            "glm": lambda: GLMLLMConfig(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "glm-4-flash"),
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
                enable_thinking=kwargs.get("enable_thinking", False)
            ),
            "ollama": lambda: OllamaLLMConfig(
                model=kwargs.get("model", "llama3"),
                base_url=kwargs.get("base_url", "http://localhost:11434"),
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096)
            ),
            "mock": lambda: MockLLMConfig(),
        }
        
        config_factory = config_map.get(provider)
        if config_factory is None:
            logger.warning(f"未知的 Agent 提供商: {provider}，使用 Mock 实现")
            config = MockLLMConfig()
        else:
            config = config_factory()
        
        return AgentFactory.create_from_config(config, system_prompt)
    
    @staticmethod
    def get_available_providers() -> list:
        """获取所有可用的提供商列表"""
        return ProviderRegistry.list_services("llm")
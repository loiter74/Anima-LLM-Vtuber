"""提供者注册中心 - 实现插件化配置和服务的核心"""

from typing import Dict, Type, Literal, Union, Annotated, Any, Callable, Optional, List
from pydantic import Field
from loguru import logger

from .base import ProviderConfig


class ProviderRegistry:
    """
    提供者注册中心（升级版）
    
    同时管理配置类和服务类，实现真正的插件化：
    - 配置类：Pydantic 模型，用于 YAML 反序列化
    - 服务类：实际执行业务逻辑的实现类
    
    示例:
        # 注册配置类
        @ProviderRegistry.register_config("llm", "openai")
        class OpenAILLMConfig(LLMBaseConfig):
            type: Literal["openai"] = "openai"
        
        # 注册服务类
        @ProviderRegistry.register_service("llm", "openai")
        class OpenAIAgent(AgentInterface):
            @classmethod
            def from_config(cls, config: OpenAILLMConfig) -> "OpenAIAgent":
                return cls(api_key=config.api_key, ...)
    """
    
    # 配置类存储: {"llm": {"openai": OpenAILLMConfig, ...}, ...}
    _configs: Dict[str, Dict[str, Type[ProviderConfig]]] = {
        "llm": {},
        "asr": {},
        "tts": {},
    }
    
    # 服务类存储: {"llm": {"openai": OpenAIAgent, ...}, ...}
    _services: Dict[str, Dict[str, Type]] = {
        "llm": {},
        "asr": {},
        "tts": {},
    }
    
    # 兼容旧 API
    _providers = _configs  # 别名，保持向后兼容
    
    # ==================== 配置类注册 ====================
    
    @classmethod
    def register_config(cls, category: Literal["llm", "asr", "tts"], provider_type: str):
        """
        装饰器：注册提供者配置类（推荐使用此名称）
        
        Args:
            category: 提供者类别 (llm/asr/tts)
            provider_type: 提供者类型标识 (如 openai, glm, ollama)
        
        Returns:
            装饰器函数
        """
        def decorator(config_class: Type[ProviderConfig]) -> Type[ProviderConfig]:
            cls._configs[category][provider_type] = config_class
            logger.debug(f"注册配置类: {category}.{provider_type} -> {config_class.__name__}")
            return config_class
        return decorator
    
    @classmethod
    def register(cls, category: Literal["llm", "asr", "tts"], provider_type: str):
        """别名：register_config（向后兼容）"""
        return cls.register_config(category, provider_type)
    
    # ==================== 服务类注册 ====================
    
    @classmethod
    def register_service(cls, category: Literal["llm", "asr", "tts"], provider_type: str):
        """
        装饰器：注册服务实现类
        
        Args:
            category: 提供者类别 (llm/asr/tts)
            provider_type: 提供者类型标识（需与配置类匹配）
        
        Returns:
            装饰器函数
        
        用法:
            @ProviderRegistry.register_service("llm", "openai")
            class OpenAIAgent(AgentInterface):
                @classmethod
                def from_config(cls, config: OpenAILLMConfig) -> "OpenAIAgent":
                    return cls(api_key=config.api_key, model=config.model)
        """
        def decorator(service_class: Type) -> Type:
            cls._services[category][provider_type] = service_class
            logger.debug(f"注册服务类: {category}.{provider_type} -> {service_class.__name__}")
            return service_class
        return decorator
    
    @classmethod
    def get_service_class(cls, category: str, provider_type: str) -> Optional[Type]:
        """
        获取服务实现类
        
        Args:
            category: 提供者类别
            provider_type: 提供者类型标识
        
        Returns:
            服务类，如果不存在则返回 None
        """
        return cls._services.get(category, {}).get(provider_type)
    
    @classmethod
    def create_service(cls, category: str, config: ProviderConfig, **extra_kwargs):
        """
        根据配置自动创建服务实例
        
        Args:
            category: 提供者类别 (llm/asr/tts)
            config: 配置对象（包含 type 字段）
            **extra_kwargs: 额外参数（如 system_prompt）
        
        Returns:
            服务实例
        
        Raises:
            ValueError: 如果找不到对应的服务类
        
        用法:
            config = OpenAILLMConfig(api_key="...", model="gpt-4")
            agent = ProviderRegistry.create_service("llm", config, system_prompt="...")
        """
        provider_type = config.type
        service_class = cls.get_service_class(category, provider_type)
        
        if service_class is None:
            raise ValueError(
                f"未找到服务实现: {category}.{provider_type}。"
                f"可用服务: {list(cls._services.get(category, {}).keys())}"
            )
        
        # 调用服务类的 from_config 方法
        if hasattr(service_class, 'from_config'):
            return service_class.from_config(config, **extra_kwargs)
        else:
            raise ValueError(
                f"服务类 {service_class.__name__} 缺少 from_config 类方法"
            )
    
    @classmethod
    def list_services(cls, category: str) -> List[str]:
        """列出某类别下所有已注册的服务"""
        return list(cls._services.get(category, {}).keys())
    
    @classmethod
    def get(cls, category: str, provider_type: str) -> Optional[Type[ProviderConfig]]:
        """
        获取指定的提供者配置类
        
        Args:
            category: 提供者类别 (llm/asr/tts)
            provider_type: 提供者类型标识
        
        Returns:
            配置类，如果不存在则返回 None
        """
        return cls._providers.get(category, {}).get(provider_type)
    
    @classmethod
    def list_providers(cls, category: str) -> List[str]:
        """
        列出某类别下所有已注册的提供者
        
        Args:
            category: 提供者类别 (llm/asr/tts)
        
        Returns:
            提供者类型标识列表
        """
        return list(cls._providers.get(category, {}).keys())
    
    @classmethod
    def get_all_providers(cls) -> Dict[str, Dict[str, Type[ProviderConfig]]]:
        """
        获取所有已注册的提供者
        
        Returns:
            所有提供者的嵌套字典
        """
        return cls._providers.copy()
    
    @classmethod
    def create_union_type(cls, category: str):
        """
        动态创建 Discriminated Union 类型
        
        Args:
            category: 提供者类别 (llm/asr/tts)
        
        Returns:
            Annotated[Union[...], Field(discriminator="type")] 类型
        
        用法:
            LLMConfig = ProviderRegistry.create_union_type("llm")
        """
        classes = list(cls._providers[category].values())
        if not classes:
            raise ValueError(f"没有注册的 {category} 提供者")
        
        # 创建 Union 类型
        union_type = Union[tuple(classes)]
        
        # 使用 discriminator 自动识别类型
        return Annotated[union_type, Field(discriminator="type")]
    
    @classmethod
    def clear(cls, category: str = None):
        """
        清除注册信息（主要用于测试）
        
        Args:
            category: 要清除的类别，如果为 None 则清除所有
        """
        if category:
            cls._providers[category] = {}
        else:
            for cat in cls._providers:
                cls._providers[cat] = {}
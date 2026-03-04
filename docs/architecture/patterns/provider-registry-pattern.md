# Provider Registry Pattern（提供者注册模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

---

## 3. Provider Registry Pattern（提供者注册模式）

### 定义

提供者注册模式使用**装饰器**自动注册服务提供商，实现零修改扩展。

### 项目应用

在 Anima 中，用于**注册 LLM/ASR/TTS 服务商**。

### 代码实现

#### 3.1 注册表

```python
# src/anima/config/core/registry.py
from typing import Type, Dict, TypeVar, Callable

T = TypeVar('T')

class ProviderRegistry:
    """服务提供商注册表"""

    # 配置类注册表: {service_type: {provider_name: config_class}}
    _configs: Dict[str, Dict[str, Type]] = {}

    # 服务类注册表: {service_type: {provider_name: service_class}}
    _services: Dict[str, Dict[str, Type]] = {}

    @classmethod
    def register_config(
        cls,
        service_type: str,
        provider_name: str
    ) -> Callable[[Type[T]], Type[T]]:
        """
        注册配置类（装饰器）

        使用示例:
            @ProviderRegistry.register_config("llm", "openai")
            class OpenAIConfig(LLMBaseConfig):
                type: Literal["openai"] = "openai"
                api_key: str
        """
        def decorator(config_class: Type[T]) -> Type[T]:
            if service_type not in cls._configs:
                cls._configs[service_type] = {}

            cls._configs[service_type][provider_name] = config_class
            return config_class

        return decorator

    @classmethod
    def register_service(
        cls,
        service_type: str,
        provider_name: str
    ) -> Callable[[Type[T]], Type[T]]:
        """
        注册服务类（装饰器）

        使用示例:
            @ProviderRegistry.register_service("llm", "openai")
            class OpenAIAgent(LLMInterface):
                @classmethod
                def from_config(cls, config):
                    return cls(api_key=config.api_key)
        """
        def decorator(service_class: Type[T]) -> Type[T]:
            if service_type not in cls._services:
                cls._services[service_type] = {}

            cls._services[service_type][provider_name] = service_class
            return service_class

        return decorator

    @classmethod
    def get_config_class(
        cls,
        service_type: str,
        provider_name: str
    ) -> Type:
        """获取配置类"""
        return cls._configs[service_type][provider_name]

    @classmethod
    def get_service_class(
        cls,
        service_type: str,
        provider_name: str
    ) -> Type:
        """获取服务类"""
        return cls._services[service_type][provider_name]
```

#### 3.2 使用装饰器注册

```python
# src/anima/services/llm/implementations/openai.py
from anima.config.core.registry import ProviderRegistry
from ..interface import LLMInterface
from ..base import LLMBaseConfig

# 1. 注册配置类
@ProviderRegistry.register_config("llm", "openai")
class OpenAIConfig(LLMBaseConfig):
    type: Literal["openai"] = "openai"
    api_key: str
    model: str = "gpt-4"
    base_url: str = "https://api.openai.com/v1"

# 2. 注册服务类
@ProviderRegistry.register_service("llm", "openai")
class OpenAIAgent(LLMInterface):
    def __init__(self, api_key: str, model: str, base_url: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = model

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """流式对话"""
        async for chunk in self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": text}],
            stream=True
        ):
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @classmethod
    def from_config(cls, config: OpenAIConfig):
        """从配置创建实例"""
        return cls(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url
        )
```

#### 3.3 工厂自动发现

```python
# src/anima/services/llm/factory.py
from anima.config.core.registry import ProviderRegistry

class LLMFactory:
    """LLM 工厂（自动发现注册的服务）"""

    @classmethod
    def create_from_config(cls, config: LLMBaseConfig) -> LLMInterface:
        """
        根据配置创建 LLM 实例

        自动从注册表中获取对应的服务类
        """
        # 从注册表获取服务类
        service_class = ProviderRegistry.get_service_class(
            "llm",           # 服务类型
            config.type      # 提供商名称 (如 "openai")
        )

        # 调用 from_config 创建实例
        return service_class.from_config(config)
```

#### 3.4 配置文件

```yaml
# config/services/llm/openai.yaml
llm_config:
  type: openai              # 提供商名称
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4"
  base_url: "https://api.openai.com/v1"
```

### 优势

1. **零修改扩展**：新增服务商不需要修改工厂代码
2. **自动发现**：装饰器自动注册，无需手动维护列表
3. **解耦**：服务定义和工厂逻辑完全解耦
4. **类型安全**：Pydantic 配置验证

### 面试要点

**Q: 这个模式和简单工厂有什么区别？**
> A: **关键区别在于自动发现**：
>
> 简单工厂：
> ```python
> class LLMFactory:
>     def create(self, provider_type):
>         if provider_type == "openai":
>             return OpenAIAgent()
>         elif provider_type == "glm":
>             return GLMAgent()
>         # 每次新增服务都要修改这里
> ```
>
> 提供者注册模式：
> ```python
> # 新增服务时，只需要加装饰器
> @ProviderRegistry.register_service("llm", "new_provider")
> class NewProviderAgent(LLMInterface):
>     pass
>
> # 工厂代码完全不需要改
> ```
>
> 这符合**开闭原则**——对扩展开放，对修改关闭。

---
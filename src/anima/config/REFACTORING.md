# 配置模块重构文档

## 概述

本次重构将 Anima 的配置模块改造为**插件化 Provider 架构**，借鉴了 Open-LLM-VTuber 的配置设计，但做了以下改进：

1. **类型安全**：使用 Pydantic Discriminated Unions 实现多态配置
2. **自动注册**：通过装饰器自动注册 Provider，无需手动维护映射表
3. **清晰分层**：core/providers/composite 三层架构
4. **合并去重**：将 CharacterConfig 合并到 PersonaConfig

## 新架构

```
config/
├── __init__.py          # 统一导出
├── core/                 # 核心基础设施
│   ├── __init__.py
│   ├── base.py          # BaseConfig, ProviderConfig 基类
│   └── registry.py      # ProviderRegistry 注册中心
├── providers/           # 提供者配置（插件化）
│   ├── __init__.py
│   ├── llm/             # LLM 提供者
│   │   ├── __init__.py  # LLMConfig Union 类型
│   │   ├── base.py      # LLMBaseConfig
│   │   ├── mock.py      # MockLLMConfig
│   │   ├── openai.py    # OpenAILLMConfig
│   │   ├── glm.py       # GLMLLMConfig
│   │   └── ollama.py    # OllamaLLMConfig
│   ├── asr/             # ASR 提供者
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── mock.py
│   │   ├── openai.py
│   │   └── glm.py
│   └── tts/             # TTS 提供者
│       ├── __init__.py
│       ├── base.py
│       ├── mock.py
│       ├── openai.py
│       ├── edge.py
│       └── glm.py
├── agent.py             # Agent 配置（组合 LLM）
├── persona.py           # 人设配置（含头像）
├── system.py            # 系统配置
└── app.py               # 应用总配置
```

## 核心概念

### 1. ProviderRegistry（提供者注册中心）

```python
from anima.config import ProviderRegistry

# 注册新提供者（自动）
@ProviderRegistry.register("llm", "my_provider")
class MyLLMConfig(LLMBaseConfig):
    type: Literal["my_provider"] = "my_provider"
    # ... 自定义字段

# 查询已注册提供者
ProviderRegistry.list_providers("llm")  # ["mock", "openai", "glm", "ollama", "my_provider"]
```

### 2. Discriminated Union（辨识联合）

```python
# YAML 中只需指定 type，自动反序列化为正确类型
llm_config:
  type: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}

# 或
llm_config:
  type: glm
  model: glm-4-flash
  enable_thinking: true
```

### 3. 添加新提供者

**步骤 1**：创建配置类

```python
# anima/config/providers/llm/azure.py
from typing import Literal, Optional
from pydantic import Field
from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig

@ProviderRegistry.register("llm", "azure")
class AzureLLMConfig(LLMBaseConfig):
    type: Literal["azure"] = "azure"
    deployment_name: str = Field(..., description="Azure 部署名称")
    endpoint: str = Field(..., description="Azure 端点")
    api_version: str = Field(default="2024-02-15-preview")
```

**步骤 2**：更新 Union 类型

```python
# anima/config/providers/llm/__init__.py
from .azure import AzureLLMConfig

LLMConfig = Annotated[
    Union[MockLLMConfig, OpenAILLMConfig, GLMLLMConfig, OllamaLLMConfig, AzureLLMConfig],
    Field(discriminator="type")
]
```

**步骤 3**：导出

```python
# anima/config/__init__.py
from .providers.llm import AzureLLMConfig
```

完成！无需修改任何业务代码。

## 服务层注册（v2 新增）

配置层和服务层现在通过 `ProviderRegistry` 统一管理：

```python
# 注册配置类
@ProviderRegistry.register_config("llm", "openai")
class OpenAILLMConfig(LLMBaseConfig):
    type: Literal["openai"] = "openai"
    ...

# 注册服务类
@ProviderRegistry.register_service("llm", "openai")
class OpenAIAgent(AgentInterface):
    
    @classmethod
    def from_config(cls, config: OpenAILLMConfig, **kwargs) -> "OpenAIAgent":
        return cls(api_key=config.api_key, model=config.model, ...)
```

**工厂简化为 Registry 查询**：

```python
# 旧版（if-elif 链）
if isinstance(config, OpenAILLMConfig):
    return OpenAIAgent(...)
elif isinstance(config, GLMLLMConfig):
    return GLMAgent(...)
# ... 每增加一个提供者都要修改这里

# 新版（Registry 自动查找）
agent = ProviderRegistry.create_service("llm", config, system_prompt="...")
```

## 与 Open-LLM-VTuber 对比

| 特性 | Open-LLM-VTuber | Anima（重构后） |
|------|-----------------|-----------------|
| 配置验证 | Pydantic BaseModel | Pydantic BaseModel |
| 多态实现 | 手动 if-elif + create_*_config | Discriminated Union（自动） |
| 提供者注册 | 隐式（需手动添加到映射） | 显式装饰器（自动注册） |
| 服务实例化 | Factory if-elif 链 | Registry 自动查找 |
| 类型安全 | 运行时验证 | 编译时 + 运行时 |
| 环境变量 | 部分支持 | 完整支持 ${VAR} 语法 |
| 人设系统 | 独立 prompts/ | 整合到 PersonaConfig |
| 扩展复杂度 | O(n) 修改多处 | O(1) 只添加新文件 |

## 环境变量支持

```yaml
# config.yaml
agent:
  llm_config:
    type: openai
    api_key: ${OPENAI_API_KEY}  # 自动展开
    base_url: ${OPENAI_BASE_URL:-https://api.openai.com/v1}  # 带默认值（计划中）
```

## 迁移指南

### 从旧版迁移

1. **LLM 配置**：移到 `agent.llm_config`
2. **Character 配置**：合并到 `persona`，使用 `persona_name` 指定
3. **ASR/TTS 配置**：结构不变，但需要添加 `type` 字段

```yaml
# 旧版 config.yaml
character:
  name: "Anima"
  avatar: "url"
llm:
  provider: "openai"
  model: "gpt-4"

# 新版 config.yaml
persona_name: "default"  # 对应 config/personas/default.yaml
agent:
  llm_config:
    type: openai
    model: gpt-4
```

## 最佳实践

1. **生产环境**：使用环境变量存储敏感信息
2. **开发环境**：使用 `mock` 提供者进行离线测试
3. **人设管理**：每个角色一个 YAML 文件在 `config/personas/`
4. **配置复用**：使用 YAML 锚点或 presets

## 计划中的增强

- [ ] 配置热重载（watch 配置文件变化）
- [ ] 配置版本迁移（自动升级旧版配置）
- [ ] 环境变量默认值语法 `${VAR:-default}`
- [ ] 配置验证 CLI 工具
- [ ] JSON Schema 导出（用于编辑器提示）
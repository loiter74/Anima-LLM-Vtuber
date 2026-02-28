# 添加新服务

> 零修改扩展 LLM/ASR/TTS/VAD 服务的完整指南

---

## 目录

1. [扩展概述](#扩展概述)
2. [步骤一：定义配置类](#步骤一定义配置类)
3. [步骤二：实现服务类](#步骤二实现服务类)
4. [步骤三：创建配置文件](#步骤三创建配置文件)
5. [步骤四：注册到 Provider](#步骤四注册到-provider)
6. [完整示例](#完整示例)

---

## 扩展概述

### 架构设计

Anima 使用 **Provider Registry Pattern** 实现零修改扩展：

```
@ProviderRegistry.register_config()  ← 注册配置类
        ↓
@ProviderRegistry.register_service()  ← 注册服务类
        ↓
YAML 配置文件  ← 服务配置
        ↓
Factory.create()  ← 工厂创建
```

### 支持的服务类型

| 类型 | 接口 | 用途 |
|------|------|------|
| **LLM** | `LLMInterface` | 对话生成 |
| **ASR** | `ASRInterface` | 语音识别 |
| **TTS** | `TTSInterface` | 语音合成 |
| **VAD** | `VADInterface` | 语音活动检测 |

---

## 步骤一：定义配置类

### 配置类结构

```python
# src/anima/config/providers/llm/my_provider.py
from pydantic import BaseModel
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("llm", "my_provider")
class MyProviderConfig(BaseModel):
    """自定义 LLM 配置类"""

    # 服务类型（必须字段）
    type: Literal["my_provider"] = "my_provider"

    # API 配置
    api_key: str
    base_url: str = "https://api.myprovider.com"
    model: str = "my-model"

    # 模型参数
    temperature: float = 0.7
    max_tokens: int = 2000

    # 可选参数
    timeout: int = 30
    retry: int = 3
```

### 配置类要求

1. **使用 `@ProviderRegistry.register_config()` 装饰器**
   ```python
   @ProviderRegistry.register_config("llm", "my_provider")
   ```

2. **定义 `type` 字段**
   ```python
   type: Literal["my_provider"] = "my_provider"
   ```

3. **继承自 `BaseModel`**
   ```python
   from pydantic import BaseModel
   class MyProviderConfig(BaseModel):
       ...
   ```

4. **定义必要参数**
   - API 密钥: `api_key: str`
   - 模型名称: `model: str`
   - 其他参数...

---

## 步骤二：实现服务类

### 服务类结构

```python
# src/anima/services/llm/implementations/my_provider.py
from typing import AsyncIterator
from anima.config.providers.llm.my_provider import MyProviderConfig
from anima.services.llm.base import LLMInterface

@ProviderRegistry.register_service("llm", "my_provider")
class MyProviderAgent(LLMInterface):
    """自定义 LLM 服务类"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 初始化客户端
        self.client = self._init_client()

    @classmethod
    def from_config(cls, config: MyProviderConfig) -> "MyProviderAgent":
        """从配置创建实例"""
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens
        )

    def _init_client(self):
        """初始化 API 客户端"""
        import httpx

        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )

    async def chat_stream(
        self,
        text: str,
        conversation_history: List[Dict] = None
    ) -> AsyncIterator[str | dict]:
        """流式对话

        Args:
            text: 用户输入
            conversation_history: 对话历史

        Yields:
            str | dict: 文本片段或结构化事件
        """
        # 构造请求
        request_data = {
            "model": self.model,
            "messages": [
                * (conversation_history or []),
                {"role": "user", "content": text}
            ],
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        # 发送请求
        response = await self.client.post(
            "/chat/completions",
            json=request_data
        )

        # 流式读取响应
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]  # 去掉 "data: " 前缀

                if data == "[DONE]":
                    break

                chunk = json.loads(data)
                content = chunk["choices"][0]["delta"].get("content", "")

                if content:
                    yield content  # 返回文本片段

    async def close(self):
        """关闭连接"""
        await self.client.aclose()
```

### 服务类要求

1. **使用 `@ProviderRegistry.register_service()` 装饰器**
   ```python
   @ProviderRegistry.register_service("llm", "my_provider")
   ```

2. **实现接口方法**
   - `async def chat_stream(text: str) -> AsyncIterator[str | dict]`
   - `async def close()` (可选)

3. **提供 `from_config()` 类方法**
   ```python
   @classmethod
   def from_config(cls, config: MyProviderConfig) -> "MyProviderAgent":
       ...
   ```

4. **处理流式响应**
   - `yield str` 返回文本片段
   - `yield dict` 返回结构化事件（可选）

---

## 步骤三：创建配置文件

### YAML 配置

```yaml
# config/services/agent/my_provider.yaml
llm_config:
  type: "my_provider"                    # 必须匹配注册的名称
  api_key: "${MY_PROVIDER_API_KEY}"      # 从环境变量读取
  base_url: "https://api.myprovider.com"
  model: "my-model"
  temperature: 0.7
  max_tokens: 2000
```

### 在主配置中使用

```yaml
# config/config.yaml
services:
  agent: my_provider  # 使用自定义服务
```

---

## 步骤四：注册到 Provider

### 自动注册

使用装饰器后，服务会自动注册到 Provider Registry：

```python
# 导入配置类（自动注册）
from anima.config.providers.llm.my_provider import MyProviderConfig

# 导入服务类（自动注册）
from anima.services.llm.implementations.my_provider import MyProviderAgent

# 现在可以通过工厂创建
from anima.services.llm.factory import LLMFactory

agent = LLMFactory.create_from_config(my_provider_config)
```

### 验证注册

```python
# 检查已注册的提供者
from anima.config.core.registry import ProviderRegistry

# 列出所有已注册的 LLM 提供者
print(ProviderRegistry.get_providers("llm"))
# 输出: ["openai", "glm", "ollama", "mock", "my_provider"]
```

---

## 完整示例

### 示例：添加 DeepSeek LLM 服务

**步骤 1: 定义配置类**

```python
# src/anima/config/providers/llm/deepseek.py
from typing import Literal
from pydantic import BaseModel
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("llm", "deepseek")
class DeepSeekConfig(BaseModel):
    type: Literal["deepseek"] = "deepseek"
    api_key: str
    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: int = 2000
```

**步骤 2: 实现服务类**

```python
# src/anima/services/llm/implementations/deepseek.py
from typing import AsyncIterator, List, Dict
from anima.config.providers.llm.deepseek import DeepSeekConfig
from anima.services.llm.base import LLMInterface
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_service("llm", "deepseek")
class DeepSeekAgent(LLMInterface):
    def __init__(self, api_key: str, model: str, temperature: float, max_tokens: int):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_config(cls, config: DeepSeekConfig) -> "DeepSeekAgent":
        return cls(
            api_key=config.api_key,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens
        )

    async def chat_stream(self, text: str, conversation_history: List[Dict] = None) -> AsyncIterator[str]:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        * (conversation_history or []),
                        {"role": "user", "content": text}
                    ],
                    "stream": True
                }
            )

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        yield content
```

**步骤 3: 创建配置文件**

```yaml
# config/services/agent/deepseek.yaml
llm_config:
  type: "deepseek"
  api_key: "${DEEPSEEK_API_KEY}"
  model: "deepseek-chat"
  temperature: 0.7
  max_tokens: 2000
```

**步骤 4: 使用服务**

```yaml
# config/config.yaml
services:
  agent: deepseek
```

```bash
# 设置环境变量
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxx

# 启动服务
python -m anima.socketio_server
```

---

## 扩展其他服务类型

### 添加 ASR 服务

```python
# src/anima/config/providers/asr/my_asr.py
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("asr", "my_asr")
class MyASRConfig(BaseModel):
    type: Literal["my_asr"] = "my_asr"
    api_key: str
    language: str = "zh"

# src/anima/services/asr/implementations/my_asr.py
from anima.services.asr.base import ASRInterface

@ProviderRegistry.register_service("asr", "my_asr")
class MyASRService(ASRInterface):
    async def transcribe(self, audio_data: np.ndarray) -> str:
        # 实现 ASR 逻辑
        pass
```

### 添加 TTS 服务

```python
# src/anima/config/providers/tts/my_tts.py
@ProviderRegistry.register_config("tts", "my_tts")
class MyTTSConfig(BaseModel):
    type: Literal["my_tts"] = "my_tts"
    api_key: str
    voice: str = "zh-cn-female"

# src/anima/services/tts/implementations/my_tts.py
from anima.services.tts.base import TTSInterface

@ProviderRegistry.register_service("tts", "my_tts")
class MyTTSService(TTSInterface):
    async def synthesize(self, text: str) -> str:
        # 返回音频文件路径
        pass
```

---

## 总结

### 扩展流程

```
1. 定义配置类 (@ProviderRegistry.register_config)
        ↓
2. 实现服务类 (@ProviderRegistry.register_service)
        ↓
3. 创建 YAML 配置文件
        ↓
4. 在主配置中使用
        ↓
5. 设置环境变量（如需要）
        ↓
6. 启动服务
```

### 关键要点

1. **装饰器**: 必须使用 `@ProviderRegistry.register_config()` 和 `@ProviderRegistry.register_service()`
2. **类型字段**: 配置类必须定义 `type: Literal["provider_name"]`
3. **工厂方法**: 服务类必须实现 `from_config()` 类方法
4. **接口方法**: 服务类必须实现接口的 `async` 方法
5. **配置文件**: YAML 配置的 `type` 必须匹配注册名称

### 简历亮点

- 设计了基于 Provider Registry 的插件架构，支持零修改扩展服务
- 新增服务只需 3 步：配置类、服务类、YAML 配置
- 已支持 12+ 种服务（GLM、OpenAI、Faster-Whisper、Edge TTS、Silero VAD 等）
- 使用装饰器 + 工厂模式，扩展难度极低（~100 行代码）

---

**最后更新**: 2026-02-28

# 设计模式详解

> 🎓 **面试重点** - 本文深入讲解项目中 6 种设计模式的实际应用

---

## 目录

1. [Factory Pattern（工厂模式）](#1-factory-pattern工厂模式)
2. [Strategy Pattern（策略模式）](#2-strategy-pattern策略模式)
3. [Provider Registry Pattern（提供者注册模式）](#3-provider-registry-pattern提供者注册模式)
4. [Observer Pattern（观察者模式）](#4-observer-pattern观察者模式)
5. [Pipeline Pattern（管道模式）](#5-pipeline-pattern管道模式)
6. [Orchestrator Pattern（编排器模式）](#6-orchestrator-pattern编排器模式)

---

## 1. Factory Pattern（工厂模式）

### 定义

工厂模式用于**封装对象创建逻辑**，客户端通过工厂类获取对象，而不需要知道具体的创建细节。

### 项目应用

在 Anima 中，工厂模式用于创建 **ASR/TTS/LLM/VAD** 服务实例。

### 类图

```
┌─────────────────────────────────────────┐
│           ASRFactory                    │
│  ┌───────────────────────────────────┐ │
│  │ + create_from_config(config)      │ │
│  │   : ASRInterface                  │ │
│  └───────────────────────────────────┘ │
│                  △                     │
│                  │                     │
│      ┌───────────┼───────────┐         │
│      │           │           │         │
│      │           │           │         │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│ │Faster.. │ │ OpenAI  │ │  GLM    │   │
│ │  ASR    │ │  ASR    │ │  ASR    │   │
│ └─────────┘ └─────────┘ └─────────┘   │
└─────────────────────────────────────────┘
```

### 代码实现

#### 1.1 接口定义

```python
# src/anima/services/asr/interface.py
from abc import ABC, abstractmethod
import numpy as np

class ASRInterface(ABC):
    """ASR 服务接口"""

    @abstractmethod
    async def transcribe(self, audio_data: np.ndarray) -> str:
        """
        将音频转换为文本

        Args:
            audio_data: 音频数据（16kHz, float32）

        Returns:
            识别出的文本
        """
        pass
```

#### 1.2 工厂类

```python
# src/anima/services/asr/factory.py
from typing import Type
from .interface import ASRInterface
from .implementations.faster_whisper import FasterWhisperASR
from .implementations.openai import OpenAIASR
from .implementations.glm import GLMASR
from .implementations.mock import MockASR

class ASRFactory:
    """ASR 工厂类"""

    # 注册表：服务商名称 -> 实现类
    _registry: dict[str, Type[ASRInterface]] = {
        "faster_whisper": FasterWhisperASR,
        "openai": OpenAIASR,
        "glm": GLMASR,
        "mock": MockASR,
    }

    @classmethod
    def create_from_config(cls, config: ASRConfig) -> ASRInterface:
        """
        根据配置创建 ASR 实例

        Args:
            config: ASR 配置对象

        Returns:
            ASR 服务实例
        """
        provider_class = cls._registry.get(config.type)

        if provider_class is None:
            raise ValueError(f"Unknown ASR provider: {config.type}")

        return provider_class.from_config(config)

    @classmethod
    def register(cls, provider_name: str, provider_class: Type[ASRInterface]):
        """
        注册新的 ASR 提供商

        Args:
            provider_name: 服务商名称
            provider_class: 实现类
        """
        cls._registry[provider_name] = provider_class
```

#### 1.3 具体实现

```python
# src/anima/services/asr/implementations/faster_whisper.py
from ..interface import ASRInterface
from ..factory import ASRFactory

class FasterWhisperASR(ASRInterface):
    """Faster-Whisper ASR 实现"""

    def __init__(self, model_size: str, device: str):
        self.model_size = model_size
        self.device = device
        self.model = None  # 延迟加载

    async def transcribe(self, audio_data: np.ndarray) -> str:
        """实现语音识别"""
        # 加载模型
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_size,
                device=self.device
            )

        # 识别
        segments, _ = self.model.transcribe(audio_data, language="zh")
        text = "".join([segment.text for segment in segments])

        return text

    @classmethod
    def from_config(cls, config: FasterWhisperConfig):
        """从配置创建实例"""
        return cls(
            model_size=config.model_size,
            device=config.device
        )

# 自动注册到工厂
ASRFactory.register("faster_whisper", FasterWhisperASR)
```

#### 1.4 使用示例

```python
# 配置文件（config/services/asr/faster_whisper.yaml）
type: faster_whisper
model_size: large-v3
device: cuda

# 使用
from anima.config import AppConfig
from anima.services.asr import ASRFactory

config = AppConfig.from_yaml("config/config.yaml")
asr_engine = ASRFactory.create_from_config(config.asr)

# 调用
audio_data = load_audio("test.wav")
text = await asr_engine.transcribe(audio_data)
print(f"识别结果: {text}")
```

### 优势

1. **解耦创建逻辑**：客户端不需要知道 `new` 的细节
2. **配置驱动**：通过配置文件切换服务商
3. **易于扩展**：新增服务商只需注册到工厂
4. **类型安全**：所有实现都继承自 `ASRInterface`

### 面试要点

**Q: 为什么用工厂模式？**
> A: 因为项目支持 6+ 种 ASR/TTS/LLM 服务商，如果不用工厂，客户端需要直接 `new` 具体类，这样：
> 1. 客户端和具体类耦合，切换服务商需要改代码
> 2. 违反了依赖倒置原则（依赖具体而非抽象）
> 3. 不利于单元测试（无法 mock）
>
> 用工厂后：
> 1. 客户端依赖 `ASRInterface` 抽象
> 2. 切换服务商只需改配置文件
> 3. 可以轻松 mock 接口进行测试

**Q: 工厂模式的缺点？**
> A: 缺点是类的数量增加了，每个具体实现都是一个类。但这个代价是值得的，因为换来的是**可维护性**和**可扩展性**。

---

## 2. Strategy Pattern（策略模式）

### 定义

策略模式用于**封装算法**，使得算法可以独立于使用它的客户端而变化。

### 项目应用

在 Anima 中，策略模式用于**情感分析算法**和**时间轴计算策略**。

### 类图

```
┌──────────────────────────────────────┐
│         IEmotionAnalyzer             │
│  ┌────────────────────────────────┐ │
│  │ + extract(text: str)           │ │
│  │   : EmotionData                │ │
│  └────────────────────────────────┘ │
│                  △                  │
│                  │                  │
│      ┌───────────┼───────────┐      │
│      │           │           │      │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  LLMTag   │  Keyword  │  Custom  │
│ Analyzer  │  Analyzer │  Analyzer │
│ └──────────┘ └──────────┘ └──────────┘
└──────────────────────────────────────┘
```

### 代码实现

#### 2.1 策略接口

```python
# src/anima/live2d/analyzers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class EmotionTag:
    """情感标签"""
    emotion: str      # 情感名称 (happy, sad, angry, etc.)
    position: int     # 在文本中的位置

@dataclass
class EmotionData:
    """情感数据"""
    emotions: List[EmotionTag]
    confidence: float  # 置信度 (0.0 - 1.0)

class IEmotionAnalyzer(ABC):
    """情感分析器接口"""

    @abstractmethod
    def extract(self, text: str, context=None) -> EmotionData:
        """
        从文本中提取情感

        Args:
            text: 输入文本
            context: 可选的上下文信息

        Returns:
            提取的情感数据
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """分析器名称"""
        pass
```

#### 2.2 具体策略 1：LLM 标签分析器

```python
# src/anima/live2d/analyzers/llm_tag_analyzer.py
import re
from .base import IEmotionAnalyzer, EmotionData, EmotionTag

class LLMTagAnalyzer(IEmotionAnalyzer):
    """
    LLM 标签情感分析器

    从 LLM 响应中提取 [happy], [sad] 等标签
    """

    # 支持的情感标签
    VALID_EMOTIONS = {
        "happy", "sad", "angry", "surprised",
        "neutral", "thinking"
    }

    def extract(self, text: str, context=None) -> EmotionData:
        """从文本中提取情感标签"""
        # 正则匹配 [emotion] 格式
        pattern = r"\[(\w+)\]"
        matches = re.finditer(pattern, text)

        emotions = []
        for match in matches:
            emotion = match.group(1).lower()
            if emotion in self.VALID_EMOTIONS:
                emotions.append(EmotionTag(
                    emotion=emotion,
                    position=match.start()
                ))

        return EmotionData(
            emotions=emotions,
            confidence=0.95 if emotions else 0.0
        )

    @property
    def name(self) -> str:
        return "llm_tag_analyzer"
```

#### 2.3 具体策略 2：关键词分析器

```python
# src/anima/live2d/analyzers/keyword_analyzer.py
from .base import IEmotionAnalyzer, EmotionData, EmotionTag

class KeywordAnalyzer(IEmotionAnalyzer):
    """
    关键词情感分析器

    通过关键词匹配推断情感
    """

    # 情感关键词字典
    EMOTION_KEYWORDS = {
        "happy": ["开心", "高兴", "快乐", "哈哈", "棒", "好"],
        "sad": ["难过", "伤心", "悲伤", "哭", "痛苦"],
        "angry": ["生气", "愤怒", "火大", "讨厌"],
        "surprised": ["惊讶", "哇", "天啊", "什么"],
        "thinking": ["让我想想", "思考", "分析", "考虑"]
    }

    def extract(self, text: str, context=None) -> EmotionData:
        """通过关键词匹配提取情感"""
        emotions = []

        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    position = text.find(keyword)
                    emotions.append(EmotionTag(
                        emotion=emotion,
                        position=position
                    ))
                    break  # 每种情感只取第一个匹配

        return EmotionData(
            emotions=emotions,
            confidence=0.75 if emotions else 0.0
        )

    @property
    def name(self) -> str:
        return "keyword_analyzer"
```

#### 2.4 工厂管理

```python
# src/anima/live2d/factory.py
from typing import Type, Dict
from .analyzers.base import IEmotionAnalyzer

class EmotionAnalyzerFactory:
    """情感分析器工厂"""

    _registry: Dict[str, Type[IEmotionAnalyzer]] = {}

    @classmethod
    def register(cls, name: str, analyzer_class: Type[IEmotionAnalyzer]):
        """注册新的分析器"""
        cls._registry[name] = analyzer_class

    @classmethod
    def create(cls, analyzer_type: str) -> IEmotionAnalyzer:
        """创建分析器实例"""
        analyzer_class = cls._registry.get(analyzer_type)

        if analyzer_class is None:
            raise ValueError(f"Unknown analyzer: {analyzer_type}")

        return analyzer_class()

# 注册分析器
from .analyzers.llm_tag_analyzer import LLMTagAnalyzer
from .analyzers.keyword_analyzer import KeywordAnalyzer

EmotionAnalyzerFactory.register("llm_tag_analyzer", LLMTagAnalyzer)
EmotionAnalyzerFactory.register("keyword_analyzer", KeywordAnalyzer)
```

#### 2.5 使用示例

```python
# 使用（可动态切换）
analyzer: IEmotionAnalyzer = EmotionAnalyzerFactory.create("llm_tag_analyzer")

text = "你好 [happy] 世界，今天 [sad] 有点难过"
emotions = analyzer.extract(text)

for emotion in emotions.emotions:
    print(f"情感: {emotion.emotion}, 位置: {emotion.position}")

# 输出:
# 情感: happy, 位置: 3
# 情感: sad, 位置: 16
```

### 优势

1. **算法可插拔**：运行时切换分析算法
2. **易于测试**：可以 mock 接口进行单元测试
3. **符合开闭原则**：新增算法不需要修改客户端代码
4. **支持 A/B 测试**：对比不同算法的效果

### 面试要点

**Q: 策略模式和工厂模式有什么区别？**
> A: **目的不同**：
> - 工厂模式：封装**对象创建**逻辑
> - 策略模式：封装**算法**逻辑
>
> **使用场景**：
> - 工厂：创建不同的 ASR 服务（对象不同）
> - 策略：不同的情感分析算法（行为不同）
>
> **结合使用**：工厂可以创建策略对象，两者经常一起使用。

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

## 4. Observer Pattern（观察者模式）

### 定义

观察者模式定义对象间的一对多依赖关系，当一个对象状态改变时，所有依赖它的对象都会收到通知。

### 项目应用

在 Anima 中，EventBus 实现了观察者模式，用于**事件发布和订阅**。

### 代码实现

#### 4.1 EventBus 实现

```python
# src/anima/eventbus/bus.py
from typing import Dict, List, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
import asyncio

class EventPriority(Enum):
    """事件优先级"""
    HIGH = 1
    NORMAL = 2
    LOW = 3

@dataclass
class Subscription:
    """订阅信息"""
    event_type: str
    handler: Callable  # Handler
    priority: EventPriority

class EventBus:
    """事件总线（观察者模式的 Subject）"""

    def __init__(self):
        # 订阅表: {event_type: [Subscription]}
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL
    ) -> Subscription:
        """
        订阅事件（注册观察者）

        Args:
            event_type: 事件类型
            handler: 处理函数
            priority: 优先级

        Returns:
            订阅对象（用于取消订阅）
        """
        subscription = Subscription(event_type, handler, priority)

        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(subscription)

        # 按优先级排序（数字越小优先级越高）
        self._subscriptions[event_type].sort(
            key=lambda sub: sub.priority.value
        )

        return subscription

    def unsubscribe(self, subscription: Subscription):
        """取消订阅"""
        event_type = subscription.event_type

        if event_type in self._subscriptions:
            self._subscriptions[event_type].remove(subscription)

    async def emit(self, event: 'OutputEvent'):
        """
        发布事件（通知所有观察者）

        Args:
            event: 事件对象
        """
        event_type = event.type

        if event_type not in self._subscriptions:
            return

        # 获取所有订阅者
        subscriptions = self._subscriptions[event_type]

        # 并发调用所有 Handler（异常隔离）
        tasks = []
        for subscription in subscriptions:
            task = self._safe_handle(subscription.handler, event)
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(self, handler: Callable, event: 'OutputEvent'):
        """
        安全调用 Handler（异常隔离）

        单个 Handler 失败不影响其他
        """
        try:
            await handler.handle(event)
        except Exception as e:
            logger.error(f"Handler failed: {e}")
            # 不中断其他 Handler
```

#### 4.2 Handler 实现

```python
# src/anima/handlers/text_handler.py
from .base_handler import BaseHandler

class TextHandler(BaseHandler):
    """文本事件处理器（观察者）"""

    def __init__(self, websocket_send):
        self.send = websocket_send

    async def handle(self, event: OutputEvent):
        """处理文本事件"""
        await self.send({
            "type": "text",
            "text": event.data,
            "seq": event.seq
        })
```

#### 4.3 使用示例

```python
# 创建 EventBus
event_bus = EventBus()

# 注册观察者
event_bus.subscribe("sentence", TextHandler(ws.send), EventPriority.HIGH)
event_bus.subscribe("audio", AudioHandler(ws.send), EventPriority.NORMAL)

# 发布事件（所有订阅者都会收到）
await event_bus.emit(OutputEvent(
    type="sentence",
    data="你好",
    seq=1
))
```

### 优势

1. **解耦**：发布者和订阅者互不依赖
2. **优先级**：控制处理顺序
3. **异常隔离**：单个失败不影响其他
4. **动态订阅**：运行时注册/取消

### 面试要点

**Q: EventBus 和简单的回调函数有什么区别？**
> A: **关键区别在于解耦和扩展性**：
>
> 简单回调：
> ```python
> class Agent:
>     def __init__(self):
>         self.on_text = None  # 回调函数
>
>     async def chat(self, text):
>         response = await self.llm.generate(text)
>         if self.on_text:  # 调用回调
>             await self.on_text(response)
>
> # 问题：
> # 1. 只能有一个回调
> # 2. Agent 需要知道回调的存在
> ```
>
> EventBus：
> ```python
> # Agent 不需要知道谁在监听
> await event_bus.emit(OutputEvent(type="sentence", data=response))
>
> # 可以有多个订阅者
> event_bus.subscribe("sentence", TextHandler(...))
> event_bus.subscribe("sentence", LogHandler(...))
> event_bus.subscribe("sentence", AnalyticsHandler(...))
> ```
>
> 这体现了**观察者模式的核心价值**——发布者和订阅者的解耦。

---

## 5. Pipeline Pattern（管道模式）

### 定义

管道模式将数据处理流程分解为多个步骤，数据按顺序通过每个步骤。

### 项目应用

在 Anima 中，用于**输入和输出数据处理**。

### 代码实现

#### 5.1 Pipeline 步骤抽象

```python
# src/anima/pipeline/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict
import numpy as np

@dataclass
class PipelineContext:
    """管道上下文（数据在步骤间传递）"""
    raw_input: Any = None           # 原始输入
    text: str = ""                 # 处理后的文本
    response: str = ""             # AI 响应
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: str = None
    skip_remaining: bool = False   # 是否跳过后续步骤

class PipelineStep(ABC):
    """管道步骤抽象基类"""

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> None:
        """
        处理上下文

        Args:
            ctx: 管道上下文
        """
        pass
```

#### 5.2 具体步骤

```python
# src/anima/pipeline/steps/asr_step.py
from ..base import PipelineStep, PipelineContext

class ASRStep(PipelineStep):
    """ASR 步骤：音频 → 文本"""

    def __init__(self, asr_engine):
        self.asr_engine = asr_engine

    async def process(self, ctx: PipelineContext) -> None:
        """处理音频输入"""
        if isinstance(ctx.raw_input, np.ndarray):
            # 音频转文本
            ctx.text = await self.asr_engine.transcribe(ctx.raw_input)
            ctx.metadata['asr_engine'] = type(self.asr_engine).__name__
        elif isinstance(ctx.raw_input, str):
            # 已经是文本，直接使用
            ctx.text = ctx.raw_input
```

```python
# src/anima/pipeline/steps/emotion_extraction_step.py
from ..base import PipelineStep, PipelineContext

class EmotionExtractionStep(PipelineStep):
    """情感提取步骤：从文本中提取情感标签"""

    def __init__(self, live2d_config=None):
        from anima.live2d.emotion_extractor import EmotionExtractor
        self.extractor = EmotionExtractor(live2d_config)

    async def process(self, ctx: PipelineContext) -> None:
        """提取情感"""
        emotions = self.extractor.extract(ctx.text)
        ctx.metadata['emotions'] = emotions
        ctx.metadata['has_emotions'] = len(emotions) > 0
```

#### 5.3 Pipeline 实现

```python
# src/anima/pipeline/input_pipeline.py
from typing import List
from .base import PipelineStep, PipelineContext

class InputPipeline:
    """输入管道"""

    def __init__(self):
        self.steps: List[PipelineStep] = []

    def add_step(self, step: PipelineStep):
        """添加步骤"""
        self.steps.append(step)
        return self

    async def process(self, raw_input: Any) -> PipelineContext:
        """
        处理输入

        数据按顺序通过每个步骤
        """
        ctx = PipelineContext(raw_input=raw_input)

        for step in self.steps:
            if ctx.skip_remaining:
                break

            await step.process(ctx)

            if ctx.error:
                # 发生错误，停止处理
                break

        return ctx
```

#### 5.4 使用示例

```python
# 创建 Pipeline
pipeline = InputPipeline()
pipeline.add_step(ASRStep(asr_engine))
pipeline.add_step(TextCleanStep())
pipeline.add_step(EmotionExtractionStep(live2d_config))

# 处理输入
ctx = await pipeline.process(audio_data)

print(f"识别文本: {ctx.text}")
print(f"情感标签: {ctx.metadata['emotions']}")
```

### 优势

1. **责任链**：数据按顺序处理
2. **可中断**：支持提前退出
3. **可复用**：步骤可以复用
4. **可扩展**：新增步骤只需 add_step

### 面试要点

**Q: Pipeline 和责任链模式有什么区别？**
> A: **概念相似，实现略有不同**：
>
> 责任链模式：
> - 每个 Handler 决定是否传递给下一个
> - 常用于审批流程、日志处理
>
> Pipeline 模式：
> - 数据**必须**通过所有步骤（除非中断）
> - 常用于数据处理、编译流程
>
> 在 Anima 中，我用 Pipeline 处理数据（ASR → 清洗 → 情感提取），用责任链处理事件（EventBus 的优先级队列）。

---

## 6. Orchestrator Pattern（编排器模式）

### 定义

编排器模式用于**管理复杂的工作流**，协调多个服务的交互。

### 项目应用

在 Anima 中，ConversationOrchestrator 编排整个对话流程。

### 代码实现

#### 6.1 Orchestrator 实现

```python
# src/anima/services/conversation/orchestrator.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class ConversationResult:
    """对话处理结果"""
    success: bool = True
    response_text: str = ""
    audio_path: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = None

class ConversationOrchestrator:
    """
    对话编排器

    整合对话流程：ASR → Agent → TTS → EventBus
    """

    def __init__(
        self,
        asr_engine,
        tts_engine,
        agent,
        websocket_send,
        session_id=None
    ):
        # 依赖的服务
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.agent = agent
        self.session_id = session_id

        # 创建 EventBus 和 Pipeline
        self.event_bus = EventBus()
        self.event_router = EventRouter(self.event_bus)
        self.input_pipeline = InputPipeline()
        self.output_pipeline = OutputPipeline()

        # 设置 Pipeline 步骤
        self._setup_pipelines()

        # 注册 Handlers
        self._setup_handlers(websocket_send)

    def _setup_pipelines(self):
        """设置 Pipeline 步骤"""
        self.input_pipeline.add_step(ASRStep(self.asr_engine))
        self.input_pipeline.add_step(TextCleanStep())
        self.input_pipeline.add_step(EmotionExtractionStep())

    def _setup_handlers(self, websocket_send):
        """注册事件处理器"""
        self.event_router.register("sentence", TextHandler(websocket_send))
        self.event_router.register("audio", AudioHandler(websocket_send))
        self.event_router.register("expression", ExpressionHandler(websocket_send))

    async def process_input(self, raw_input) -> ConversationResult:
        """
        处理用户输入

        编排完整的对话流程
        """
        try:
            # 1. InputPipeline 处理
            ctx = await self.input_pipeline.process(raw_input)

            if ctx.error:
                return ConversationResult(success=False, error=ctx.error)

            # 2. Agent 对话
            response_text = ""
            async for chunk in self.agent.chat_stream(ctx.text):
                response_text += chunk

                # 3. OutputPipeline 处理（流式）
                await self.output_pipeline.process_chunk(chunk)

            return ConversationResult(
                success=True,
                response_text=response_text,
                metadata=ctx.metadata
            )

        except Exception as e:
            logger.error(f"Conversation failed: {e}")
            return ConversationResult(success=False, error=str(e))

    def start(self):
        """启动编排器"""
        self.event_router.setup()

    def stop(self):
        """停止编排器"""
        self.event_router.clear()
```

#### 6.2 使用示例

```python
# 创建编排器
orchestrator = ConversationOrchestrator(
    asr_engine=asr_engine,
    tts_engine=tts_engine,
    agent=agent,
    websocket_send=ws.send,
    session_id="user-001"
)

# 启动
orchestrator.start()

# 处理输入
result = await orchestrator.process_input(audio_data)

print(f"AI 回复: {result.response_text}")

# 停止
orchestrator.stop()
```

### 优势

1. **统一管理**：管理整个对话流程的生命周期
2. **依赖注入**：所有依赖通过构造函数注入
3. **易于测试**：可以 mock 依赖进行单元测试
4. **清晰职责**：编排器只负责编排，不负责具体逻辑

### 面试要点

**Q: 为什么需要 Orchestrator？不能直接在 Handler 里调用吗？**
> A: **关键在于职责分离和生命周期管理**：
>
> 如果在 Handler 里直接调用：
> ```python
> class TextHandler:
#     async def handle(self, event):
#         # ❌ Handler 直接调用 Agent，耦合度高
#         response = await self.agent.chat(event.data)
#         await self.send(response)
# ```
>
> 用 Orchestrator：
> ```python
> # ✅ Orchestrator 负责编排，Handler 只负责发送
# orchestrator = ConversationOrchestrator(agent, asr, tts)
# result = await orchestrator.process_input(audio)
# ```
>
> **优势**：
> 1. **职责单一**：Orchestrator 编排流程，Handler 处理事件
> 2. **生命周期**：Orchestrator 管理服务的初始化和销毁
> 3. **可测试性**：可以 mock 整个 Orchestrator
> 4. **可复用**：Orchestrator 可以在不同场景复用

---

## 总结

### 设计模式对比表

| 模式 | 目的 | 项目应用场景 | 优势 |
|------|------|--------------|------|
| **Factory** | 封装对象创建 | ASR/TTS/LLM 服务创建 | 解耦创建逻辑，配置驱动 |
| **Strategy** | 封装算法 | 情感分析器、时间轴策略 | 算法可插拔，易于 A/B 测试 |
| **Provider Registry** | 自动注册 | 服务商注册 | 零修改扩展，符合开闭原则 |
| **Observer** | 事件发布订阅 | EventBus 事件系统 | 解耦发布者和订阅者 |
| **Pipeline** | 数据处理流程 | 输入/输出管道 | 责任链，可中断，可复用 |
| **Orchestrator** | 工作流编排 | 对话流程编排 | 统一管理，生命周期控制 |

### 面试准备

**必答问题**：
1. 能画出 6 种模式的类图
2. 能说明每种模式的应用场景
3. 能对比相似模式的区别
4. 能说明模式的优缺点

### 相关文档

- [技术亮点](../overview/highlights.md) - 项目亮点总结
- [数据流设计](./data-flow.md) - 完整的数据流架构
- [事件系统](./event-system.md) - EventBus 详细实现

---

**最后更新**: 2026-02-28

# Factory Pattern（工厂模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

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
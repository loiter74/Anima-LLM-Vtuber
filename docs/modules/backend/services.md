# 服务层架构

> 服务层（ASR/TTS/LLM/VAD）的接口设计和工厂模式实现

---

## 目录

1. [服务层概览](#服务层概览)
2. [ASR 服务](#asr-服务)
3. [TTS 服务](#tts-服务)
4. [LLM 服务](#llm-服务)
5. [VAD 服务](#vad-服务)
6. [工厂模式](#工厂模式)
7. [使用示例](#使用示例)

---

## 服务层概览

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      ServiceContext                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ asr_engine: ASRInterface                               │  │
│  │ tts_engine: TTSInterface                               │  │
│  │ llm_engine: LLMInterface                               │  │
│  │ vad_engine: VADInterface                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                           ↓                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ load_from_config(config)                               │  │
│  │   - ASRFactory.create_from_config(config.asr)          │  │
│  │   - TTSFactory.create_from_config(config.tts)          │  │
│  │   - LLMFactory.create_from_config(config.agent)        │  │
│  │   - VADFactory.create_from_config(config.vad)          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      ConversationOrchestrator               │
│  使用服务层提供的接口：                                      │
│  - await asr_engine.transcribe(audio_data)                 │
│  - await llm_engine.chat_stream(text)                      │
│  - await tts_engine.synthesize(text)                       │
│  - vad_engine.process(audio_chunk)                         │
└─────────────────────────────────────────────────────────────┘
```

---

## ASR 服务

### 接口定义

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

        Raises:
            NotImplementedError: 子类必须实现
        """
        pass

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """
        获取支持的音频格式

        Returns:
            支持的格式列表，如 ["wav", "mp3"]
        """
        pass
```

### 实现类

#### 1. Faster-Whisper ASR

```python
# src/anima/services/asr/implementations/faster_whisper.py
from ..interface import ASRInterface

class FasterWhisperASR(ASRInterface):
    """Faster-Whisper ASR 实现"""

    def __init__(self, model_size: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None  # 延迟加载

    async def transcribe(self, audio_data: np.ndarray) -> str:
        """识别语音"""
        # 延迟加载模型（首次调用时）
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )

        # 识别
        segments, info = self.model.transcribe(
            audio_data,
            language="zh",
            word_timestamps=True
        )

        # 拼接文本
        text = "".join([segment.text for segment in segments])

        return text

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            model_size=config.model_size,
            device=config.device,
            compute_type=config.compute_type
        )
```

#### 2. OpenAI ASR

```python
# src/anima/services/asr/implementations/openai.py
from ..interface import ASRInterface

class OpenAIASR(ASRInterface):
    """OpenAI Whisper ASR 实现"""

    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(self, audio_data: np.ndarray) -> str:
        """识别语音"""
        import io
        import tempfile

        # 保存为临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            import wave
            with wave.open(tmp.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_data.tobytes())

            # 调用 API
            with open(tmp.name, 'rb') as audio_file:
                transcript = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file
                )

        return transcript.text

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            api_key=config.api_key,
            model=config.model
        )
```

---

## TTS 服务

### 接口定义

```python
# src/anima/services/tts/interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator

class TTSInterface(ABC):
    """TTS 服务接口"""

    @abstractmethod
    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """
        将文本转换为语音

        Args:
            text: 要转换的文本

        Yields:
            音频数据块（mp3/wav 格式）

        Raises:
            NotImplementedError: 子类必须实现
        """
        pass

    @abstractmethod
    def get_supported_voices(self) -> list[str]:
        """获取支持的音色列表"""
        pass
```

### 实现类

#### 1. Edge TTS

```python
# src/anima/services/tts/implementations/edge.py
from ..interface import TTSInterface
import edge_tts

class EdgeTTS(TTSInterface):
    """Edge TTS 实现（免费，无配额限制）"""

    def __init__(self, voice: str, rate: str, volume: str):
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.communicate = edge_tts.CommunicateEdgeTextToSpeech(
            voice, rate, volume
        )

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """合成语音"""
        # 生成音频
        await self.communicate.SaveAudio(text, "output.mp3")

        # 读取音频文件
        with open("output.mp3", "rb") as f:
            yield f.read()

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            voice=config.voice,
            rate=config.rate,
            volume=config.volume
        )
```

#### 2. OpenAI TTS

```python
# src/anima/services/tts/implementations/openai.py
from ..interface import TTSInterface
from openai import AsyncOpenAI

class OpenAITTS(TTSInterface):
    """OpenAI TTS 实现"""

    def __init__(self, api_key: str, model: str, voice: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """合成语音"""
        response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text
        )

        # 流式返回
        await response.stream_to_file("output.mp3")

        with open("output.mp3", "rb") as f:
            yield f.read()

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            api_key=config.api_key,
            model=config.model,
            voice=config.voice
        )
```

---

## LLM 服务

### 接口定义

```python
# src/anima/services/llm/interface.py
from abc import ABC, abstractmethod
from typing import AsyncIterator, Union

class LLMInterface(ABC):
    """LLM 服务接口"""

    @abstractmethod
    async def chat_stream(self, text: str) -> AsyncIterator[str | dict]:
        """
        流式对话

        Args:
            text: 用户输入

        Yields:
            文本片段或结构化事件：
            - str: 文本 Token
            - dict: {"type": "sentence", "content": "完整句子"}

        Raises:
            NotImplementedError: 子类必须实现
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取模型信息"""
        pass
```

### 实现类

#### 1. GLM Agent

```python
# src/anima/services/llm/implementations/glm.py
from zai import ZhipuAiClient
from ..interface import LLMInterface

class GLMAgent(LLMInterface):
    """智谱 GLM Agent 实现"""

    def __init__(self, api_key: str, model: str):
        self.client = ZhipuAiClient(api_key=api_key)
        self.model = model

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """流式对话"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": text}],
            stream=True
        )

        async for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            api_key=config.api_key,
            model=config.model
        )
```

#### 2. Ollama Agent

```python
# src/anima/services/llm/implementations/ollama.py
from ollama import AsyncClient
from ..interface import LLMInterface

class OllamaAgent(LLMInterface):
    """Ollama Agent 实现（本地运行）"""

    def __init__(self, model: str, host: str):
        self.client = AsyncClient(host=host)
        self.model = model

    async def chat_stream(self, text: str) -> AsyncIterator[str]:
        """流式对话"""
        response = await self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": text}],
            stream=True
        )

        async for chunk in response:
            yield chunk['message']['content']

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            model=config.model,
            host=config.host
        )
```

---

## VAD 服务

### 接口定义

```python
# src/anima/services/vad/interface.py
from abc import ABC, abstractmethod
from typing import Iterator, Optional

class VADInterface(ABC):
    """VAD 服务接口"""

    @abstractmethod
    def process(self, audio_chunk: list) -> Iterator[bytes]:
        """
        处理音频流，检测语音活动

        Args:
            audio_chunk: 音频数据块（16kHz, float32）

        Yields:
            检测到的完整语音数据

        Returns:
            当检测到语音结束时返回完整的音频数据
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """重置状态"""
        pass
```

### 实现类

#### Silero VAD

```python
# src/anima/services/vad/implementations/silero.py
from ..interface import VADInterface

class SileroVAD(VADInterface):
    """Silero VAD 实现（基于深度学习）"""

    def __init__(self, threshold: float, min_silence_duration: int):
        import torch
        from silero_vad_utils import get_speech_timestamps

        # 加载模型
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False
        )

        self.threshold = threshold
        self.min_silence_duration = min_silence_duration

        # 状态
        self.buffer = []
        self.is_speeching = False

    def process(self, audio_chunk: list) -> Iterator[bytes]:
        """检测语音活动"""
        import numpy as np

        # 转换为 NumPy 数组
        audio_int16 = np.array(audio_chunk, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0

        # VAD 检测
        speeches = self.get_speech_timestamps(audio_float32, self.threshold)

        # 累积音频数据
        for speech in speeches:
            start, end = speech
            self.buffer.extend(audio_int16[start:end].tolist())

            # 检测到语音结束
            if self._is_silence_long_enough():
                yield np.array(self.buffer, dtype=np.int16).tobytes()
                self.buffer = []

    def _is_silence_long_enough(self) -> bool:
        """检测沉默时长是否足够"""
        # 简化版实现
        return len(self.buffer) > 16000 * self.min_silence_duration

    def reset(self) -> None:
        """重置状态"""
        self.buffer = []
        self.is_speeching = False

    @classmethod
    def from_config(cls, config):
        """从配置创建"""
        return cls(
            threshold=config.threshold,
            min_silence_duration=config.min_silence_duration
        )
```

---

## 工厂模式

### ASR Factory

```python
# src/anima/services/asr/factory.py
from typing import Type, Dict
from .interface import ASRInterface
from ..config import ASRConfig

class ASRFactory:
    """ASR 工厂"""

    _registry: Dict[str, Type[ASRInterface]] = {
        "faster_whisper": FasterWhisperASR,
        "openai": OpenAIASR,
        "glm": GLMASR,
        "mock": MockASR,
    }

    @classmethod
    def create_from_config(cls, config: ASRConfig) -> ASRInterface:
        """根据配置创建 ASR 实例"""
        provider_class = cls._registry.get(config.type)

        if provider_class is None:
            raise ValueError(f"Unknown ASR provider: {config.type}")

        return provider_class.from_config(config)

    @classmethod
    def register(cls, provider_name: str, provider_class: Type[ASRInterface]):
        """注册新的 ASR 提供商"""
        cls._registry[provider_name] = provider_class
```

### TTS Factory

```python
# src/anima/services/tts/factory.py
class TTSFactory:
    """TTS 工厂"""

    _registry: Dict[str, Type[TTSInterface]] = {
        "openai": OpenAITTS,
        "glm": GLMTTS,
        "edge": EdgeTTS,
        "mock": MockTTS,
    }

    @classmethod
    def create_from_config(cls, config: TTSConfig) -> TTSInterface:
        """根据配置创建 TTS 实例"""
        provider_class = cls._registry.get(config.type)

        if provider_class is None:
            raise ValueError(f"Unknown TTS provider: {config.type}")

        return provider_class.from_config(config)
```

### LLM Factory

```python
# src/anima/services/llm/factory.py
class LLMFactory:
    """LLM 工厂"""

    _registry: Dict[str, Type[LLMInterface]] = {
        "openai": OpenAIAgent,
        "glm": GLMAgent,
        "ollama": OllamaAgent,
        "mock": MockAgent,
    }

    @classmethod
    def create_from_config(cls, config: LLMConfig) -> LLMInterface:
        """根据配置创建 LLM 实例"""
        provider_class = cls._registry.get(config.type)

        if provider_class is None:
            raise ValueError(f"Unknown LLM provider: {config.type}")

        return provider_class.from_config(config)
```

---

## 使用示例

### 配置文件

```yaml
# config/services/asr/faster_whisper.yaml
type: faster_whisper
model_size: large-v3
device: cuda
compute_type: float16

# config/services/tts/edge.yaml
type: edge
voice: zh-CN-XiaoxiaoNeural
rate: "+0%"
volume: "+50%"

# config/services/llm/glm.yaml
llm_config:
  type: glm
  api_key: "${GLM_API_KEY}"
  model: glm-4
```

### 使用服务

```python
# 在 ServiceContext 中使用
from anima.config import AppConfig
from anima.services.asr import ASRFactory
from anima.services.tts import TTSFactory
from anima.services.llm import LLMFactory

config = AppConfig.from_yaml("config/config.yaml")

# 创建服务实例
asr_engine = ASRFactory.create_from_config(config.asr)
tts_engine = TTSFactory.create_from_config(config.tts)
llm_engine = LLMFactory.create_from_config(config.agent)

# 使用服务
async def process_audio(audio_data: np.ndarray):
    # ASR: 音频转文本
    text = await asr_engine.transcribe(audio_data)

    # LLM: 流式对话
    response = ""
    async for chunk in llm_engine.chat_stream(text):
        response += chunk
        print(chunk, end='')

    # TTS: 文本转音频
    audio_chunks = []
    async for chunk in tts_engine.synthesize(response):
        audio_chunks.append(chunk)

    return b''.join(audio_chunks)
```

---

## 总结

### 服务层特点

1. **接口驱动**：所有服务都实现对应的 Interface
2. **工厂创建**：通过 Factory 模式创建实例
3. **配置驱动**：通过 YAML 配置文件切换服务
4. **延迟加载**：首次使用时才加载模型（节省内存）

### 优势

- ✅ **解耦**：高层模块只依赖接口，不依赖具体实现
- ✅ **可扩展**：新增服务只需注册到工厂
- ✅ **可测试**：可以 mock 接口进行单元测试
- ✅ **可配置**：通过配置文件切换服务商

---

## 相关文档

- [设计模式详解](../../architecture/design-patterns.md) - 工厂模式详细说明
- [可扩展性设计](../../architecture/extensibility.md) - 如何新增服务
- [添加新服务](../../development/adding-services.md) - 扩展指南

---

**最后更新**: 2026-02-28

# 管道系统

> Pipeline 模式的实现：InputPipeline 和 OutputPipeline
>
> ⚠️ **注意**：部分示例代码使用旧的组件名称（如 `EmotionExtractor`），这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> - `EmotionExtractor` → `StandaloneLLMTagAnalyzer`
>
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

---

## 目录

1. [管道模式概述](#管道模式概述)
2. [InputPipeline](#inputpipeline)
3. [OutputPipeline](#outputpipeline)
4. [Pipeline Steps](#pipeline-steps)
5. [使用示例](#使用示例)

---

## 管道模式概述

### 定义

管道模式（Pipeline Pattern）将数据处理流程分解为多个步骤，数据按顺序通过每个步骤。

### 在 Anima 中的应用

```
InputPipeline: 音频 → 文本 → 情感
OutputPipeline: LLM Token → 句子 → 事件
```

---

## InputPipeline

### 职责

处理用户输入（文本或音频）：

1. **ASRStep**：音频转文本
2. **TextCleanStep**：文本清洗
3. **EmotionExtractionStep**：情感提取

### 代码实现

```python
# src/anima/pipeline/input_pipeline.py
from typing import List, Optional
from .base import PipelineStep, PipelineContext
from .steps.asr_step import ASRStep
from .steps.text_clean_step import TextCleanStep
from .steps.emotion_extraction_step import EmotionExtractionStep

class InputPipeline:
    """输入管道"""

    def __init__(self):
        self.steps: List[PipelineStep] = []

    def add_step(self, step: PipelineStep) -> 'InputPipeline':
        """添加步骤"""
        self.steps.append(step)
        return self

    async def process(self, raw_input) -> PipelineContext:
        """
        处理输入

        数据按顺序通过每个步骤
        """
        ctx = PipelineContext(raw_input=raw_input)

        for step in self.steps:
            if ctx.skip_remaining:
                logger.debug("[InputPipeline] Skipping remaining steps")
                break

            await step.process(ctx)

            if ctx.error:
                logger.error(f"[InputPipeline] Error in {step.__class__.__name__}: {ctx.error}")
                break

        return ctx
```

---

## OutputPipeline

### 职责

处理 LLM 流式响应，转换为事件流：

1. **累积 Tokens**：将 LLM Token 累积成句子
2. **触发事件**：每完成一句，发射 `sentence` 事件
3. **TTS 合成**：同时触发 TTS 音频合成
4. **事件发射**：发射 `audio` 事件

### 代码实现

```python
# src/anima/pipeline/output_pipeline.py
from typing import AsyncIterator
from ..core.events import OutputEvent, EventType
from ..eventbus import EventBus

class OutputPipeline:
    """输出管道"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.accumulator = ""

    async def process(
        self,
        chunks: AsyncIterator[str | dict]
    ) -> ConversationResult:
        """
        处理 LLM 流式响应

        Args:
            chunks: LLM Token 流

        Returns:
            对话结果
        """
        response_text = ""
        seq = 0

        async for chunk in chunks:
            # 处理不同类型的 chunk
            if isinstance(chunk, str):
                # 文本 Token
                self.accumulator += chunk
                response_text += chunk

                # 检查是否完成一句
                if self._is_sentence_complete():
                    sentence = self._extract_sentence()

                    # 发射文本事件
                    await self.event_bus.emit(OutputEvent(
                        type=EventType.SENTENCE,
                        data=sentence,
                        seq=seq
                    ))

                    seq += 1

            elif isinstance(chunk, dict):
                # 结构化事件
                await self.event_bus.emit(OutputEvent(**chunk))

        return ConversationResult(
            success=True,
            response_text=response_text
        )

    def _is_sentence_complete(self) -> bool:
        """检查当前累积的文本是否构成完整句子"""
        # 简单实现：根据标点符号判断
        for char in ['。', '！', '？', '.', '!', '?']:
            if char in self.accumulator:
                return True
        return False

    def _extract_sentence(self) -> str:
        """提取完整句子"""
        sentence = self.accumulator.strip()
        self.accumulator = ""
        return sentence
```

---

## Pipeline Steps

### ASRStep

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

### TextCleanStep

```python
# src/anima/pipeline/steps/text_clean_step.py
from ..base import PipelineStep, PipelineContext
import re

class TextCleanStep(PipelineStep):
    """文本清洗步骤"""

    async def process(self, ctx: PipelineContext) -> None:
        """清洗文本"""
        # 移除多余空格
        ctx.text = re.sub(r'\s+', ' ', ctx.text)

        # 移除特殊字符
        ctx.text = ctx.text.strip()

        # 移除 Markdown 符号（如果需要）
        ctx.text = ctx.text.replace('*', '')
```

### EmotionExtractionStep

```python
# src/anima/pipeline/steps/emotion_extraction_step.py
from ..base import PipelineStep, PipelineContext

class EmotionExtractionStep(PipelineStep):
    """情感提取步骤"""

    def __init__(self, live2d_config=None):
        from anima.live2d.emotion_extractor import EmotionExtractor
        self.extractor = EmotionExtractor(live2d_config)

    async def process(self, ctx: PipelineContext) -> None:
        """提取情感"""
        emotions = self.extractor.extract(ctx.text)
        ctx.metadata['emotions'] = emotions
        ctx.metadata['has_emotions'] = len(emotions) > 0
```

---

## 使用示例

### 创建 Pipeline

```python
# 在 ConversationOrchestrator 中创建
from anima.pipeline import InputPipeline, OutputPipeline
from anima.pipeline.steps import ASRStep, TextCleanStep, EmotionExtractionStep

input_pipeline = InputPipeline()
input_pipeline.add_step(ASRStep(asr_engine))
input_pipeline.add_step(TextCleanStep())
input_pipeline.add_step(EmotionExtractionStep(live2d_config))

output_pipeline = OutputPipeline(event_bus)
```

### 使用 Pipeline

```python
# 输入处理
ctx = await input_pipeline.process(audio_data)
print(f"识别文本: {ctx.text}")
print(f"情感标签: {ctx.metadata['emotions']}")

# 输出处理
async for chunk in llm_agent.chat_stream("你好"):
    await output_pipeline.process(chunk)
```

---

## 总结

### Pipeline 优势

1. **责任链**：数据按顺序处理
2. **可中断**：支持 `skip_remaining` 提前退出
3. **可复用**：步骤可以复用
4. **可扩展**：新增步骤只需 `add_step`

---

**最后更新**: 2026-02-28

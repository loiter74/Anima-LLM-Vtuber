# Pipeline Pattern（管道模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

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
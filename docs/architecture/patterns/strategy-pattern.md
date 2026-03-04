# Strategy Pattern（策略模式）

> 🎓 **面试重点** - 设计模式实际应用
> 
> ⚠️ **注意**：部分示例代码使用旧的组件名称，这些在 v0.6.0 (2026-03-01) 已被新架构替代。
> 请参考 [CLAUDE.md](../../../CLAUDE.md) 了解最新的架构。

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
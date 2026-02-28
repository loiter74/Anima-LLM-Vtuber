# Live2D 扩展指南

> 自定义情感分析器和时间轴策略的完整指南

---

## 目录

1. [扩展架构](#扩展架构)
2. [扩展情感分析器](#扩展情感分析器)
3. [扩展时间轴策略](#扩展时间轴策略)
4. [使用自定义组件](#使用自定义组件)
5. [完整示例](#完整示例)

---

## 扩展架构

### 插件系统

Live2D 情感系统采用 **Strategy Pattern + Factory Pattern** 实现插件化：

```
IEmotionAnalyzer (Interface)
        ↑
        ├── LL MTagAnalyzer
        ├── KeywordAnalyzer
        └── YourCustomAnalyzer  ← 自定义分析器

ITimelineStrategy (Interface)
        ↑
        ├── PositionBasedStrategy
        ├── DurationBasedStrategy
        └── YourCustomStrategy  ← 自定义策略
```

### 工厂模式

```python
# src/anima/live2d/factory.py
class EmotionAnalyzerFactory:
    """情感分析器工厂"""

    _analyzers = {
        "llm_tag_analyzer": LL MTagAnalyzer,
        "keyword_analyzer": KeywordAnalyzer,
        # 可动态注册新分析器
    }

    @classmethod
    def create(cls, analyzer_type: str, **kwargs) -> IEmotionAnalyzer:
        """创建分析器实例"""
        analyzer_class = cls._analyzers.get(analyzer_type)
        if analyzer_class is None:
            raise ValueError(f"Unknown analyzer: {analyzer_type}")
        return analyzer_class(**kwargs)

    @classmethod
    def register(cls, analyzer_type: str, analyzer_class: Type[IEmotionAnalyzer]):
        """注册新分析器"""
        cls._analyzers[analyzer_type] = analyzer_class
```

---

## 扩展情感分析器

### 步骤 1: 实现接口

```python
# src/anima/live2d/analyzers/custom_analyzer.py
from typing import List
from anima.live2d.analyzers.base import IEmotionAnalyzer, EmotionData
from anima.live2d.emotion_extractor import EmotionTag

class CustomEmotionAnalyzer(IEmotionAnalyzer):
    """自定义情感分析器"""

    def __init__(self, custom_param: str = "default"):
        """
        Args:
            custom_param: 自定义参数
        """
        self.custom_param = custom_param

    def analyze(
        self,
        text: str,
        emotion_tags: List[EmotionTag]
    ) -> EmotionData:
        """分析文本情感

        Args:
            text: LLM 响应文本（已去除情感标签）
            emotion_tags: 提取的情感标签列表

        Returns:
            EmotionData: 分析结果
        """
        # 1. 优先使用 LLM 标签
        if emotion_tags:
            emotions = [tag.emotion for tag in emotion_tags]
            return EmotionData(
                emotions=emotions,
                primary=emotions[0],
                confidence=1.0
            )

        # 2. 自定义分析逻辑
        # 例如：基于文本长度、标点符号、关键词等
        primary = self._detect_emotion(text)
        confidence = self._calculate_confidence(text, primary)

        return EmotionData(
            emotions=[primary],
            primary=primary,
            confidence=confidence
        )

    def _detect_emotion(self, text: str) -> str:
        """检测情感（示例）"""
        # 自定义逻辑：根据文本内容判断情感
        if "!" in text or "！" in text:
            return "surprised"
        elif "?" in text or "？" in text:
            return "thinking"
        elif any(word in text for word in ["开心", "快乐", "高兴"]):
            return "happy"
        else:
            return "neutral"

    def _calculate_confidence(self, text: str, emotion: str) -> float:
        """计算置信度（示例）"""
        # 自定义逻辑：根据文本特征计算置信度
        if emotion == "neutral":
            return 0.5
        else:
            return 0.8
```

### 步骤 2: 注册到工厂

```python
# src/anima/live2d/factory.py
from anima.live2d.analyzers.custom_analyzer import CustomEmotionAnalyzer

# 方法 1: 直接注册
EmotionAnalyzerFactory.register("custom_analyzer", CustomEmotionAnalyzer)

# 方法 2: 使用装饰器自动注册
@EmotionAnalyzerFactory.register_analyzer("custom_analyzer")
class CustomEmotionAnalyzer(IEmotionAnalyzer):
    # ...
    pass
```

### 步骤 3: 配置使用

```yaml
# config/features/live2d.yaml
emotion_system:
  analyzer:
    type: "custom_analyzer"    # 使用自定义分析器
    custom_param: "my_value"   # 传递自定义参数
```

---

## 扩展时间轴策略

### 步骤 1: 实现接口

```python
# src/anima/live2d/strategies/custom_strategy.py
from typing import List
from anima.live2d.strategies.base import ITimelineStrategy, TimelineSegment
from anima.live2d.analyzers.base import EmotionData

class CustomTimelineStrategy(ITimelineStrategy):
    """自定义时间轴策略"""

    def __init__(
        self,
        min_duration: float = 1.0,
        max_duration: float = 5.0,
        transition_duration: float = 0.3
    ):
        """
        Args:
            min_duration: 最小时长（秒）
            max_duration: 最大时长（秒）
            transition_duration: 过渡时长（秒）
        """
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.transition_duration = transition_duration

    def calculate(
        self,
        audio_duration: float,
        emotion_data: EmotionData
    ) -> List[TimelineSegment]:
        """计算情感时间轴

        Args:
            audio_duration: 音频总时长（秒）
            emotion_data: 情感数据

        Returns:
            List[TimelineSegment]: 时间轴片段列表
        """
        segments = []
        emotions = emotion_data.emotions

        if not emotions:
            return [TimelineSegment("neutral", 0.0, audio_duration)]

        # 自定义策略：基于情感权重和位置
        # 例如：主要情感占 60%，次要情感各占 20%

        # 1. 确定主要情感
        primary = emotion_data.primary
        primary_weight = 0.6

        # 2. 计算主要情感时长
        primary_duration = audio_duration * primary_weight
        primary_duration = max(
            self.min_duration,
            min(self.max_duration, primary_duration)
        )

        segments.append(TimelineSegment(
            emotion=primary,
            time=0.0,
            duration=primary_duration
        ))

        # 3. 分配剩余时间给其他情感
        remaining_duration = audio_duration - primary_duration
        current_time = primary_duration

        for emotion in emotions:
            if emotion == primary:
                continue

            # 平均分配剩余时间
            emotion_duration = remaining_duration / (len(emotions) - 1)
            emotion_duration = max(
                self.min_duration,
                min(self.max_duration, emotion_duration)
            )

            segments.append(TimelineSegment(
                emotion=emotion,
                time=current_time,
                duration=emotion_duration
            ))

            current_time += emotion_duration

        return segments
```

### 步骤 2: 注册到工厂

```python
# src/anima/live2d/factory.py
from anima.live2d.strategies.custom_strategy import CustomTimelineStrategy

# 注册自定义策略
TimelineStrategyFactory.register("custom_strategy", CustomTimelineStrategy)
```

### 步骤 3: 配置使用

```yaml
# config/features/live2d.yaml
emotion_system:
  strategy:
    type: "custom_strategy"          # 使用自定义策略
    min_duration: 1.0                # 传递自定义参数
    max_duration: 5.0
    transition_duration: 0.3
```

---

## 使用自定义组件

### 在 UnifiedEventHandler 中使用

```python
# src/anima/handlers/unified_event_handler.py
from anima.live2d.factory import (
    create_emotion_analyzer,
    create_timeline_strategy
)

# 创建自定义组件
analyzer = create_emotion_analyzer(
    analyzer_type="custom_analyzer",
    config={"custom_param": "my_value"}
)

strategy = create_timeline_strategy(
    strategy_type="custom_strategy",
    config={
        "min_duration": 1.0,
        "max_duration": 5.0,
        "transition_duration": 0.3
    }
)

# 创建 Handler
handler = UnifiedEventHandler(
    websocket_send=ws.send,
    analyzer=analyzer,
    strategy=strategy
)
```

### 工厂函数

```python
# src/anima/live2d/factory.py

def create_emotion_analyzer(
    analyzer_type: str,
    config: dict = None
) -> IEmotionAnalyzer:
    """创建情感分析器

    Args:
        analyzer_type: 分析器类型
        config: 配置参数

    Returns:
        IEmotionAnalyzer: 分析器实例
    """
    config = config or {}
    return EmotionAnalyzerFactory.create(analyzer_type, **config)

def create_timeline_strategy(
    strategy_type: str,
    config: dict = None
) -> ITimelineStrategy:
    """创建时间轴策略

    Args:
        strategy_type: 策略类型
        config: 配置参数

    Returns:
        ITimelineStrategy: 策略实例
    """
    config = config or {}
    return TimelineStrategyFactory.create(strategy_type, **config)
```

---

## 完整示例

### 示例 1: 基于机器学习的情感分析器

```python
# src/anima/live2d/analyzers/ml_analyzer.py
from typing import List
from anima.live2d.analyzers.base import IEmotionAnalyzer, EmotionData
from anima.live2d.emotion_extractor import EmotionTag

class MLEmotionAnalyzer(IEmotionAnalyzer):
    """基于机器学习的情感分析器"""

    def __init__(self, model_path: str):
        """
        Args:
            model_path: ML 模型路径
        """
        self.model_path = model_path
        self.model = self._load_model()

    def _load_model(self):
        """加载 ML 模型"""
        # 示例：使用 transformers 加载 BERT 模型
        from transformers import pipeline

        return pipeline(
            "text-classification",
            model=self.model_path,
            return_all_scores=True
        )

    def analyze(
        self,
        text: str,
        emotion_tags: List[EmotionTag]
    ) -> EmotionData:
        # 优先使用 LLM 标签
        if emotion_tags:
            emotions = [tag.emotion for tag in emotion_tags]
            return EmotionData(
                emotions=emotions,
                primary=emotions[0],
                confidence=1.0
            )

        # 使用 ML 模型预测
        results = self.model(text)[0]

        # 找出得分最高的情感
        top_result = max(results, key=lambda x: x["score"])

        # 映射到 Live2D 情感
        emotion_map = {
            "JOY": "happy",
            "SADNESS": "sad",
            "ANGER": "angry",
            "SURPRISE": "surprised",
            "NEUTRAL": "neutral"
        }

        primary = emotion_map.get(top_result["label"], "neutral")
        confidence = top_result["score"]

        return EmotionData(
            emotions=[primary],
            primary=primary,
            confidence=confidence
        )
```

**使用**:
```yaml
# config/features/live2d.yaml
emotion_system:
  analyzer:
    type: "ml_analyzer"
    model_path: "models/emotion-bert"
```

### 示例 2: 基于音频特征的时间轴策略

```python
# src/anima/live2d/strategies/audio_based_strategy.py
from typing import List
from anima.live2d.strategies.base import ITimelineStrategy, TimelineSegment
from anima.live2d.analyzers.base import EmotionData

class AudioBasedTimelineStrategy(ITimelineStrategy):
    """基于音频特征的时间轴策略"""

    def __init__(
        self,
        volume_threshold: float = 0.3,
        min_pause_duration: float = 0.5
    ):
        """
        Args:
            volume_threshold: 音量阈值（用于检测停顿）
            min_pause_duration: 最小停顿时长
        """
        self.volume_threshold = volume_threshold
        self.min_pause_duration = min_pause_duration

    def calculate(
        self,
        audio_duration: float,
        emotion_data: EmotionData,
        volume_envelope: List[float] = None
    ) -> List[TimelineSegment]:
        """根据音频音量包络计算时间轴"""
        segments = []
        emotions = emotion_data.emotions

        if not emotions:
            return [TimelineSegment("neutral", 0.0, audio_duration)]

        # 1. 分析音量包络，检测停顿
        pauses = self._detect_pauses(volume_envelope)

        # 2. 在停顿处切换情感
        current_time = 0.0
        emotion_index = 0

        for pause_time in pauses:
            # 当前情感持续时间
            duration = pause_time - current_time

            if duration > 0:
                segments.append(TimelineSegment(
                    emotion=emotions[emotion_index % len(emotions)],
                    time=current_time,
                    duration=duration
                ))

                current_time = pause_time
                emotion_index += 1

        # 3. 添加最后一个片段
        if current_time < audio_duration:
            segments.append(TimelineSegment(
                emotion=emotions[emotion_index % len(emotions)],
                time=current_time,
                duration=audio_duration - current_time
            ))

        return segments

    def _detect_pauses(self, volume_envelope: List[float]) -> List[float]:
        """检测停顿点（返回时间列表）"""
        pauses = []
        below_threshold = False
        below_start = 0.0

        for i, volume in enumerate(volume_envelope):
            time = i / 50.0  # 假设 50Hz 采样

            if volume < self.volume_threshold:
                if not below_threshold:
                    below_threshold = True
                    below_start = time
            else:
                if below_threshold:
                    # 停顿结束
                    duration = time - below_start
                    if duration >= self.min_pause_duration:
                        pauses.append(below_start)
                    below_threshold = False

        return pauses
```

**使用**:
```yaml
# config/features/live2d.yaml
emotion_system:
  strategy:
    type: "audio_based"
    volume_threshold: 0.3
    min_pause_duration: 0.5
```

---

## 总结

### 扩展流程

```
1. 实现接口 (IEmotionAnalyzer / ITimelineStrategy)
        ↓
2. 注册到工厂 (Factory.register())
        ↓
3. 配置使用 (YAML 配置)
        ↓
4. 运行时加载 (Factory.create())
```

### 关键要点

1. **接口实现**: 必须实现 `analyze()` 或 `calculate()` 方法
2. **工厂注册**: 使用 `Factory.register()` 注册新组件
3. **配置驱动**: 通过 YAML 配置指定使用哪个组件
4. **参数传递**: 支持通过 `config` 字典传递自定义参数

### 简历亮点

- 设计了插件化情感系统，支持自定义分析器和策略
- 通过 Strategy Pattern + Factory Pattern 实现零修改扩展
- 已支持 2 种分析器、3 种时间轴策略
- 扩展难度极低：实现 1 个接口方法，约 50-100 行代码

---

**最后更新**: 2026-02-28

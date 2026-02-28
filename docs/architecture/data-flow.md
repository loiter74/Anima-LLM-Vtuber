# 数据流设计

> 本文档详细说明 Anima 的五层数据流架构

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        用户输入                              │
│  (文本: "你好" / 音频: waveform)                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: InputPipeline（输入管道）                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Step 1: ASRStep - 音频转文本                        │   │
│  │   Input: np.ndarray (audio)                         │   │
│  │   Output: "你好"                                     │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Step 2: TextCleanStep - 文本清洗                   │   │
│  │   Input: "你好"                                     │   │
│  │   Output: "你好" (移除多余空格、标点)                │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Step 3: EmotionExtractionStep - 情感提取            │   │
│  │   Input: "你好"                                     │   │
│  │   Output: EmotionData(emotions=[], confidence=0.0) │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Agent（LLM 对话）                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Input: "你好"                                        │   │
│  │ Process: LLM.stream_chat()                          │   │
│  │ Output: AsyncIterator[str]                          │   │
│  │   - chunk 1: "你"                                   │   │
│  │   - chunk 2: "好"                                   │   │
│  │   - chunk 3: "！"                                   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: OutputPipeline（输出管道）                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Process: 逐块处理 LLM 响应                          │   │
│  │   - 累积 chunks 为句子                             │   │
│  │   - 每完成一句，发射 sentence 事件                │   │
│  │   - 同时触发 TTS 合成                               │   │
│  │ Output: OutputEvent stream                          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: EventBus（事件总线）                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Event: OutputEvent(                                  │   │
│  │   type="sentence",                                  │   │
│  │   data="你好！",                                     │   │
│  │   seq=1                                             │   │
│  │ )                                                   │   │
│  │ Process: 按优先级通知订阅者                         │   │
│  │   - HIGH Priority: TextHandler                     │   │
│  │   - NORMAL Priority: AudioHandler                  │   │
│  │   - LOW Priority: LogHandler                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: Handlers（事件处理器）                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ TextHandler:                                        │   │
│  │   - 发送文本到前端                                  │   │
│  │   ws.send({type: "text", text: "你好！"})           │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ AudioHandler:                                       │   │
│  │   - 调用 TTS 合成音频                               │   │
│  │   - 发送音频到前端                                  │   │
│  │   ws.send({type: "audio", data: base64_audio})     │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Live2DHandler:                                      │   │
│  │   - 提取情感                                        │   │
│  │   - 计算时间轴                                      │   │
│  │   - 发送表情事件到前端                              │   │
│  │   ws.send({type: "expression", data: "happy"})     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      前端实时渲染                            │
│  - 文本显示在聊天界面                                       │
│  - 音频自动播放                                             │
│  - Live2D 模型同步表情和唇同步                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 详细流程

### 场景 1：文本输入

```
用户输入文本 "你好"
   ↓
WebSocket Event: text_input
   ↓
ConversationOrchestrator.process_input("你好")
   ↓
InputPipeline.process("你好")
   ├─ ASRStep: 跳过（已是文本）
   ├─ TextCleanStep: 清洗文本
   └─ EmotionExtractionStep: 提取情感
   ↓
Agent.chat_stream("你好")
   ↓
LLM 返回: "你好！我是 Anima。"
   ↓
OutputPipeline 处理
   ↓
EventBus.emit(sentence)
   ↓
TextHandler 发送文本到前端
   ↓
前端显示: "你好！我是 Anima。"
```

### 场景 2：音频输入（带 VAD）

```
用户说话（麦克风）
   ↓
前端录音: AudioRecorder
   ↓
WebSocket Event: raw_audio_data (流式发送)
   ↓
VADProcessor 检测语音活动
   ├─ 检测到说话开始 → 开始录音
   ├─ 检测到说话结束 → 触发 mic_audio_end
   ↓
WebSocket Event: mic_audio_end
   ↓
ConversationOrchestrator.process_input(audio_buffer)
   ↓
InputPipeline.process(audio_buffer)
   ├─ ASRStep: 音频转文本 → "你好"
   ├─ TextCleanStep: 清洗文本
   └─ EmotionExtractionStep: 提取情感
   ↓
Agent.chat_stream("你好")
   ↓
LLM 返回: "你好！我是 Anima。"
   ↓
OutputPipeline 处理
   ├─ TTS 合成音频
   └─ 提取情感: [neutral]
   ↓
EventBus.emit(audio)
EventBus.emit(expression)
   ↓
AudioHandler 发送音频
Live2DHandler 发送表情事件
   ↓
前端播放音频 + Live2D 同步表情
```

### 场景 3：带情感的对话

```
用户: "今天天气真好"
   ↓
LLM 返回: "是呀 [happy] ，我也觉得很开心！"
   ↓
OutputPipeline 处理
   ├─ EmotionExtractionStep 提取情感
   │   Input: "是呀 [happy] ，我也觉得很开心！"
   │   Output: EmotionData(emotions=[EmotionTag("happy", 3)])
   ├─ TTS 合成音频
   │   AudioAnalyzer.compute_volume_envelope(audio)
   │   Output: volumes=[0.1, 0.2, 0.5, ...] (50Hz 采样)
   └─ EmotionTimelineCalculator.calculate()
   │   Input: emotions=[EmotionTag("happy", 3)], text="...", duration=5.0
   │   Output: segments=[TimelineSegment(emotion="happy", time=0.5, duration=2.0)]
   ↓
EventBus.emit(audio_with_expression)
   ↓
前端接收:
{
  "type": "audio_with_expression",
  "audio_data": "base64_encoded_audio",
  "volumes": [0.1, 0.2, 0.5, ...],
  "expressions": {
    "segments": [
      {"emotion": "neutral", "time": 0.0, "duration": 0.5},
      {"emotion": "happy", "time": 0.5, "duration": 2.0},
      {"emotion": "neutral", "time": 2.5, "duration": 2.5}
    ],
    "total_duration": 5.0
  }
}
   ↓
前端播放:
├─ 音频播放
├─ LipSyncEngine: 根据 volumes 更新嘴部参数 (30fps)
└─ ExpressionTimeline: 根据 segments 切换表情
```

---

## 数据结构流转

### PipelineContext

```python
# InputPipeline 中的数据载体
@dataclass
class PipelineContext:
    raw_input: Union[str, np.ndarray]  # 原始输入
    text: str                           # 处理后的文本
    metadata: Dict[str, Any]           # 元数据
        - emotions: List[EmotionTag]
        - has_emotions: bool
        - asr_engine: str
```

### OutputEvent

```python
# EventBus 中的事件载体
@dataclass
class OutputEvent:
    type: str          # 事件类型 (sentence, audio, expression, etc.)
    data: Any          # 事件数据
    seq: int           # 序号
    metadata: Dict     # 元数据
```

### 音频+表情事件

```python
# Live2D 统一事件
{
    "type": "audio_with_expression",
    "audio_data": "base64_encoded_mp3",
    "format": "mp3",
    "volumes": [0.1, 0.2, 0.5, ...],      # 50Hz 音量包络
    "expressions": {
        "segments": [                       # 情感时间轴
            {
                "emotion": "neutral",
                "time": 0.0,
                "duration": 0.5,
                "intensity": 0.0
            },
            {
                "emotion": "happy",
                "time": 0.5,
                "duration": 2.0,
                "intensity": 0.8
            }
        ],
        "total_duration": 5.0
    },
    "text": "是呀 ，我也觉得很开心！",
    "seq": 1
}
```

---

## 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| **端到端延迟** | < 500ms | 从用户说话到听到回复 |
| **首字延迟** | < 200ms | LLM 第一个 token 返回 |
| **TTS 延迟** | < 300ms | 文本到音频合成 |
| **音量包络采样** | 50Hz | 每 20ms 一个采样点 |
| **嘴部参数更新** | 30fps | 每 33ms 更新一次 |
| **情感切换延迟** | < 100ms | 表情切换响应时间 |

---

## 相关文档

- [设计模式详解](./design-patterns.md) - Pipeline 和 EventBus 的设计模式
- [事件系统](./event-system.md) - EventBus 详细实现
- [项目技术亮点](../overview/highlights.md) - 技术亮点总结

---

**最后更新**: 2026-02-28

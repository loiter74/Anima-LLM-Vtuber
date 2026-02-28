# API 参考

> WebSocket 事件和 API 接口的完整文档

---

## 目录

1. [WebSocket 事件](#WebSocket-事件)
2. [后端接口](#后端接口)
3. [前端 API](#前端-API)
4. [数据结构](#数据结构)

---

## WebSocket 事件

### 客户端 → 服务器

#### text_input

发送文本消息

**事件数据**:
```typescript
{
  "type": "text_input",
  "data": {
    "text": "你好",                    // 必需，用户输入文本
    "metadata": {                      // 可选，元数据
      "skip_history": false            // 是否跳过历史记录
    },
    "from_name": "user"                // 可选，发送者名称
  }
}
```

**示例**:
```javascript
socket.emit("text_input", {
  text: "你好",
  metadata: {
    skip_history: false
  },
  from_name: "user"
})
```

---

#### raw_audio_data

发送原始音频数据（用于 VAD）

**事件数据**:
```typescript
{
  "type": "raw_audio_data",
  "data": {
    "audio": [0.1, 0.2, 0.3, ...]     // 必需，Float32Array 音频数据
  }
}
```

**示例**:
```javascript
const audioData = new Float32Array(audioBuffer)
socket.emit("raw_audio_data", {
  audio: Array.from(audioData)
})
```

---

#### mic_audio_end

标记音频输入结束（手动模式）

**事件数据**:
```typescript
{
  "type": "mic_audio_end",
  "data": {}
}
```

**示例**:
```javascript
socket.emit("mic_audio_end", {})
```

---

#### interrupt_signal

中断当前响应

**事件数据**:
```typescript
{
  "type": "interrupt_signal",
  "data": {}
}
```

**示例**:
```javascript
socket.emit("interrupt_signal", {})
```

---

### 服务器 → 客户端

#### connection-established

连接建立成功

**事件数据**:
```typescript
{
  "type": "connection-established",
  "data": {
    "session_id": "abc123",           // 会话 ID
    "message": "连接成功"
  }
}
```

---

#### text / sentence

流式文本片段

**事件数据**:
```typescript
{
  "type": "text",                     // 或 "sentence"
  "data": "你好",                     // 文本片段
  "seq": 1,                          // 序列号
  "is_complete": false,              // 是否完成
  "metadata": {}                     // 元数据
}
```

**说明**:
- 每个完整句子会触发一次事件
- 流式返回时，`seq` 会递增
- `is_complete=true` 表示整个响应结束

---

#### audio_with_expression

音频 + 音量包络 + 情感时间轴（统一事件）

**事件数据**:
```typescript
{
  "type": "audio_with_expression",
  "data": {
    "audio_data": "base64_encoded_audio",  // Base64 编码的音频
    "format": "mp3",                       // 音频格式
    "volumes": [0.1, 0.2, 0.3, ...],       // 50Hz 音量包络
    "expressions": {
      "segments": [
        {
          "emotion": "happy",              // 情感名称
          "time": 0.0,                     // 开始时间（秒）
          "duration": 2.5                  // 持续时间（秒）
        },
        {
          "emotion": "neutral",
          "time": 2.5,
          "duration": 1.0
        }
      ],
      "total_duration": 3.5                // 总时长（秒）
    },
    "text": "你好！ 很高兴见到你！",      // 清洗后的文本（去除标签）
    "seq": 1                              // 序列号
  }
}
```

---

#### transcript

ASR 识别结果

**事件数据**:
```typescript
{
  "type": "transcript",
  "data": {
    "text": "你好",                     // 识别文本
    "confidence": 0.95,                // 置信度（可选）
    "is_final": true                   // 是否最终结果
  }
}
```

---

#### expression

Live2D 表情控制（状态基）

**事件数据**:
```typescript
{
  "type": "expression",
  "data": {
    "expression": "happy",             // 表情名称
    "metadata": {}                     // 元数据
  }
}
```

**可用表情**:
- `idle` - 空闲
- `listening` - 听话
- `thinking` - 思考
- `speaking` - 说话
- `surprised` - 惊讶
- `sad` - 伤心
- `happy` - 开心
- `neutral` - 中性
- `angry` - 生气

---

#### control

控制信号

**事件数据**:
```typescript
{
  "type": "control",
  "data": {
    "action": "start-mic",             // 动作名称
    "params": {}                       // 参数（可选）
  }
}
```

**可用动作**:
- `start-mic` - 开始麦克风录音
- `stop-mic` - 停止麦克风录音
- `interrupt` - 中断当前响应
- `clear-history` - 清除历史记录

---

#### error

错误事件

**事件数据**:
```typescript
{
  "type": "error",
  "data": {
    "code": "ASR_ERROR",               // 错误代码
    "message": "语音识别失败",          // 错误消息
    "details": {}                      // 详细信息（可选）
  }
}
```

---

## 后端接口

### Pipeline API

#### InputPipeline

处理用户输入

```python
# src/anima/pipeline/input_pipeline.py
class InputPipeline:
    async def process(self, raw_input: Union[str, np.ndarray]) -> PipelineContext:
        """处理输入

        Args:
            raw_input: 原始输入（文本或音频）

        Returns:
            PipelineContext: 处理结果
        """
```

#### OutputPipeline

处理 LLM 输出

```python
# src/anima/pipeline/output_pipeline.py
class OutputPipeline:
    async def process(
        self,
        chunks: AsyncIterator[str | dict]
    ) -> ConversationResult:
        """处理输出

        Args:
            chunks: LLM Token 流

        Returns:
            ConversationResult: 对话结果
        """
```

---

### Service API

#### LLM Service

```python
# src/anima/services/llm/base.py
class LLMInterface(ABC):
    @abstractmethod
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
```

#### ASR Service

```python
# src/anima/services/asr/base.py
class ASRInterface(ABC):
    @abstractmethod
    async def transcribe(self, audio_data: np.ndarray) -> str:
        """语音识别

        Args:
            audio_data: 音频数据 (16kHz, float32)

        Returns:
            str: 识别文本
        """
```

#### TTS Service

```python
# src/anima/services/tts/base.py
class TTSInterface(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> str:
        """语音合成

        Args:
            text: 待合成文本

        Returns:
            str: 音频文件路径
        """
```

#### VAD Service

```python
# src/anima/services/vad/base.py
class VADInterface(ABC):
    @abstractmethod
    async def detect_speech_end(self, audio_chunks: List[np.ndarray]) -> bool:
        """检测语音结束

        Args:
            audio_chunks: 音频块列表

        Returns:
            bool: 是否检测到语音结束
        """
```

---

### EventBus API

```python
# src/anima/eventbus/bus.py
class EventBus:
    def subscribe(
        self,
        event_type: str,
        handler: BaseHandler,
        priority: EventPriority = EventPriority.NORMAL
    ) -> Subscription:
        """订阅事件

        Args:
            event_type: 事件类型
            handler: 处理器
            priority: 优先级

        Returns:
            Subscription: 订阅对象
        """

    async def emit(self, event: OutputEvent):
        """发布事件

        Args:
            event: 输出事件
        """
```

---

## 前端 API

### Hooks

#### useConversation

对话 Hook

```typescript
// frontend/features/conversation/hooks/useConversation.ts
interface UseConversationReturn {
  // 状态
  messages: Message[]
  isConnected: boolean
  isTyping: boolean
  currentResponse: string

  // 方法
  sendMessage: (text: string) => Promise<void>
  clearMessages: () => void
  interrupt: () => void
}

function useConversation(): UseConversationReturn
```

**示例**:
```typescript
const { messages, sendMessage, isConnected } = useConversation()

await sendMessage("你好")
```

---

#### useLive2D

Live2D Hook

```typescript
// frontend/features/live2d/hooks/useLive2D.ts
interface UseLive2DOptions {
  modelPath: string
  scale?: number
  position?: { x: number; y: number }
}

interface UseLive2DReturn {
  isLoaded: boolean
  setExpression: (expression: string) => void
  playAudioWithExpressions: (
    audioData: string,
    volumes: number[],
    segments: TimelineSegment[]
  ) => void
}

function useLive2D(options: UseLive2DOptions): UseLive2DReturn
```

**示例**:
```typescript
const { isLoaded, setExpression } = useLive2D({
  modelPath: "/live2d/hiyori/Hiyori.model3.json"
})

setExpression("happy")
```

---

#### useAudioRecorder

音频录制 Hook

```typescript
// frontend/features/audio/hooks/useAudioRecorder.ts
interface UseAudioRecorderReturn {
  isRecording: boolean
  audioLevel: number
  startRecording: () => void
  stopRecording: () => Promise<string | null>
}

function useAudioRecorder(): UseAudioRecorderReturn
```

**示例**:
```typescript
const { isRecording, startRecording, stopRecording } = useAudioRecorder()

startRecording()
// ...
const audioData = await stopRecording()
```

---

### Services

#### SocketService

Socket.IO 服务

```typescript
// frontend/features/connection/services/SocketService.ts
class SocketService {
  // 连接
  connect(): void

  // 断开
  disconnect(): void

  // 发送事件
  send(event: string, data: any): void

  // 订阅事件
  on(event: string, handler: (data: any) => void): void

  // 取消订阅
  off(event: string, handler?: (data: any) => void): void
}
```

**示例**:
```typescript
const socketService = SocketService.getInstance()

socketService.connect()
socketService.on("text", (data) => console.log(data))
socketService.send("text_input", { text: "你好" })
```

---

#### Live2DService

Live2D 服务

```typescript
// frontend/features/live2d/services/Live2DService.ts
class Live2DService {
  // 加载模型
  async loadModel(): Promise<void>

  // 设置表情
  setExpression(expression: string): void

  // 播放音频和表情
  async playAudioWithExpressions(
    audioData: string,
    volumes: number[],
    segments: TimelineSegment[]
  ): Promise<void>

  // 销毁
  destroy(): void
}
```

---

## 数据结构

### Message

```typescript
// frontend/shared/types/conversation.ts
interface Message {
  id: string                       // 消息 ID
  role: 'user' | 'ai' | 'system'   // 角色
  content: string                  // 内容
  timestamp: number                // 时间戳
}
```

---

### TimelineSegment

```typescript
// frontend/features/live2d/types/index.ts
interface TimelineSegment {
  emotion: string                  // 情感名称
  time: number                     // 开始时间（秒）
  duration: number                 // 持续时间（秒）
  intensity?: number               // 强度（可选）
}
```

---

### EmotionData

```python
# src/anima/live2d/analyzers/base.py
@dataclass
class EmotionData:
    emotions: List[str]            # 情感列表
    primary: str                   # 主要情感
    confidence: float              # 置信度 (0.0 - 1.0)
```

---

### OutputEvent

```python
# src/anima/core/events.py
@dataclass
class OutputEvent:
    type: str                      # 事件类型
    data: Any                      # 事件数据
    seq: int                       # 序列号
    metadata: Dict = None          # 元数据
```

---

### ConversationResult

```python
# src/anima/services/conversation/orchestrator.py
@dataclass
class ConversationResult:
    success: bool                  # 是否成功
    response_text: str             # 响应文本
    audio_path: Optional[str]      # 音频路径
    error: Optional[str]           # 错误信息
    metadata: dict                 # 元数据
```

---

## 总结

### API 使用流程

**客户端发送消息**:
```javascript
socket.emit("text_input", { text: "你好" })
```

**服务器处理流程**:
```python
InputPipeline.process(text)
  → ASRStep.transcribe() (如果是音频)
  → TextCleanStep.clean()
  → EmotionExtractionStep.extract()
  → LLMService.chat_stream()
  → OutputPipeline.process(chunks)
  → EventBus.emit(OutputEvent)
  → Handler.handle() → WebSocket.send()
```

**客户端接收响应**:
```javascript
socket.on("text", (data) => {
  // 更新 UI
  addMessage({ role: 'ai', content: data.text })
})

socket.on("audio_with_expression", (data) => {
  // 播放音频
  playAudio(data.audio_data, data.volumes, data.expressions)
})
```

---

**最后更新**: 2026-02-28

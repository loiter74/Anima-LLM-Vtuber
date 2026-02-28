# 开发最佳实践

> 代码规范、性能优化和架构设计建议

---

## 目录

1. [代码规范](#代码规范)
2. [异步编程](#异步编程)
3. [错误处理](#错误处理)
4. [性能优化](#性能优化)
5. [测试策略](#测试策略)

---

## 代码规范

### Python 代码风格

**遵循 PEP 8**:
```python
# ✅ 好的做法
class ConversationOrchestrator:
    def __init__(self, service_context: ServiceContext):
        self.service_context = service_context
        self.input_pipeline = InputPipeline()
        self.output_pipeline = OutputPipeline()

    async def process_input(self, user_input: str) -> ConversationResult:
        """处理用户输入"""
        try:
            ctx = await self.input_pipeline.process(user_input)
            return await self._process_conversation(ctx)
        except Exception as e:
            logger.error(f"处理输入失败: {e}")
            return ConversationResult(success=False, error=str(e))

# ❌ 不好的做法
class conversationOrchestrator:
    def __init__(self,sc):
        self.sc=sc
        self.p1=InputPipeline()
    def process(self,i):
        ctx=self.p1.process(i)
        return self._process(ctx)
```

**使用类型注解**:
```python
# ✅ 好的做法
from typing import AsyncIterator, List, Dict, Optional

async def chat_stream(
    self,
    text: str,
    conversation_history: Optional[List[Dict]] = None
) -> AsyncIterator[str | dict]:
    """流式对话"""
    ...

# ❌ 不好的做法
async def chat_stream(self, text, history=None):
    """流式对话"""
    ...
```

**文档字符串**:
```python
# ✅ 好的做法（Google 风格）
async def process_input(self, user_input: str) -> ConversationResult:
    """处理用户输入并生成响应

    Args:
        user_input: 用户输入文本或音频数据

    Returns:
        ConversationResult: 对话结果，包含响应文本、音频路径等

    Raises:
        ValueError: 输入格式无效
        RuntimeError: 服务不可用

    Example:
        >>> result = await orchestrator.process_input("你好")
        >>> print(result.response_text)
        "你好！有什么我可以帮助你的吗？"
    """
    ...

# ❌ 不好的做法
async def process_input(self, user_input):
    # 处理输入
    ...
```

### TypeScript 代码风格

**使用函数式组件**:
```typescript
// ✅ 好的做法
export function ChatPanel() {
  const { messages, sendMessage } = useConversation()
  const [isRecording, startRecording, stopRecording] = useAudioRecorder()

  return (
    <div>
      <MessageList messages={messages} />
      <InputBox onSend={sendMessage} />
      <AudioButton
        isRecording={isRecording}
        onStart={startRecording}
        onStop={stopRecording}
      />
    </div>
  )
}

// ❌ 不好的做法（使用 class 组件）
export class ChatPanel extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      messages: [],
      isRecording: false
    }
  }
  // ...
}
```

**使用自定义 Hook**:
```typescript
// ✅ 好的做法
function useLive2D(options: UseLive2DOptions) {
  const [isLoaded, setIsLoaded] = useState(false)
  const serviceRef = useRef<Live2DService | null>(null)

  useEffect(() => {
    const service = new Live2DService(canvasRef.current, options)
    serviceRef.current = service

    service.loadModel().then(() => setIsLoaded(true))

    return () => service.destroy()
  }, [options])

  return { isLoaded, setExpression: serviceRef.current?.setExpression }
}

// ❌ 不好的做法（逻辑耦合在组件中）
function Live2DViewer() {
  const [model, setModel] = useState(null)
  useEffect(() => {
    // 50 行模型加载逻辑
    // ...
  }, [])
  // ...
}
```

---

## 异步编程

### Python Async/Await

**始终使用 async/await**:
```python
# ✅ 好的做法
async def process_conversation(self, text: str) -> ConversationResult:
    # I/O 操作使用 await
    ctx = await self.input_pipeline.process(text)
    response_stream = await self.agent.chat_stream(text)

    # 流式处理
    async for chunk in response_stream:
        await self.event_bus.emit(OutputEvent(type="sentence", data=chunk))

    return ConversationResult(success=True)

# ❌ 不好的做法（阻塞）
def process_conversation(self, text: str) -> ConversationResult:
    ctx = self.input_pipeline.process(text)  # 阻塞调用
    response = self.agent.chat(text)  # 阻塞调用
    return ConversationResult(success=True)
```

**并发执行**:
```python
# ✅ 好的做法（并发）
async def process_multiple_inputs(self, inputs: List[str]) -> List[ConversationResult]:
    tasks = [self.process_input(input) for input in inputs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# ❌ 不好的做法（串行）
async def process_multiple_inputs(self, inputs: List[str]) -> List[ConversationResult]:
    results = []
    for input in inputs:
        result = await self.process_input(input)  # 等待每个完成
        results.append(result)
    return results
```

**超时控制**:
```python
# ✅ 好的做法
async def process_with_timeout(self, text: str, timeout: float = 30.0) -> ConversationResult:
    try:
        result = await asyncio.wait_for(
            self.process_input(text),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"处理超时: {text}")
        return ConversationResult(success=False, error="Timeout")

# ❌ 不好的做法（无超时控制）
async def process(self, text: str) -> ConversationResult:
    return await self.process_input(text)  # 可能永久挂起
```

### TypeScript Async/Await

**错误处理**:
```typescript
// ✅ 好的做法
async function sendMessage(text: string) {
  try {
    await socketService.send("text_input", { text })
    setIsTyping(true)
  } catch (error) {
    console.error("发送失败:", error)
    setError("发送失败，请重试")
  }
}

// ❌ 不好的做法（无错误处理）
async function sendMessage(text: string) {
  await socketService.send("text_input", { text })
  setIsTyping(true)
}
```

**使用 Promise.all**:
```typescript
// ✅ 好的做法（并发）
async function loadResources() {
  const [model, config, audio] = await Promise.all([
    loadLive2DModel(),
    loadConfig(),
    loadAudio()
  ])
  return { model, config, audio }
}

// ❌ 不好的做法（串行）
async function loadResources() {
  const model = await loadLive2DModel()
  const config = await loadConfig()
  const audio = await loadAudio()
  return { model, config, audio }
}
```

---

## 错误处理

### Python 异常处理

**具体异常捕获**:
```python
# ✅ 好的做法
async def transcribe_audio(self, audio_path: str) -> str:
    try:
        return await self.asr_service.transcribe(audio_path)
    except FileNotFoundError:
        logger.error(f"音频文件不存在: {audio_path}")
        return ""
    except ASRException as e:
        logger.error(f"ASR 识别失败: {e}")
        return ""
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return ""

# ❌ 不好的做法（捕获所有异常）
async def transcribe_audio(self, audio_path: str) -> str:
    try:
        return await self.asr_service.transcribe(audio_path)
    except Exception:  # 吞掉所有异常
        return ""
```

**异常链**:
```python
# ✅ 好的做法（保留原始异常）
async def process_input(self, text: str) -> ConversationResult:
    try:
        return await self._process_conversation(text)
    except ValueError as e:
        raise ValueError(f"输入处理失败: {text}") from e

# ❌ 不好的做法（丢失原始异常）
async def process_input(self, text: str) -> ConversationResult:
    try:
        return await self._process_conversation(text)
    except ValueError as e:
        raise ValueError("输入处理失败")  # 丢失原始错误信息
```

### TypeScript 错误处理

**使用 Result 类型**:
```typescript
// ✅ 好的做法
type Result<T, E = Error> = {
  success: true
  data: T
} | {
  success: false
  error: E
}

async function transcribeAudio(audioPath: string): Promise<Result<string>> {
  try {
    const text = await asrService.transcribe(audioPath)
    return { success: true, data: text }
  } catch (error) {
    return { success: false, error: error as Error }
  }
}

// ❌ 不好的做法（抛出异常）
async function transcribeAudio(audioPath: string): Promise<string> {
  return await asrService.transcribe(audioPath)  // 可能抛出异常
}
```

**错误边界**:
```typescript
// ✅ 好的做法（使用错误边界）
function ErrorBoundary({ children }: { children: React.ReactNode }) {
  const [error, setError] = useState<Error | null>(null)

  if (error) {
    return <div>错误: {error.message}</div>
  }

  return (
    <ErrorBoundaryFallback on Error={setError}>
      {children}
    </ErrorBoundaryFallback>
  )
}

// ❌ 不好的做法（无错误边界）
function App() {
  return (
    <ChatPanel />  // 任何错误都会导致白屏
  )
}
```

---

## 性能优化

### 避免重复计算

**使用缓存**:
```python
# ✅ 好的做法（使用 lru_cache）
from functools import lru_cache

class AudioAnalyzer:
    @lru_cache(maxsize=128)
    def calculate_volume_envelope_from_file(self, audio_path: str) -> List[float]:
        """带缓存的音量包络计算"""
        # ...
        pass

# ❌ 不好的做法（每次重新计算）
class AudioAnalyzer:
    def calculate_volume_envelope_from_file(self, audio_path: str) -> List[float]:
        # 每次都重新计算
        pass
```

**React 性能优化**:
```typescript
// ✅ 好的做法（使用 useMemo）
function MessageList({ messages }: { messages: Message[] }) {
  const sortedMessages = useMemo(
    () => messages.sort((a, b) => b.timestamp - a.timestamp),
    [messages]
  )

  return (
    <div>
      {sortedMessages.map(msg => (
        <Message key={msg.id} message={msg} />
      ))}
    </div>
  )
}

// ❌ 不好的做法（每次重新排序）
function MessageList({ messages }: { messages: Message[] }) {
  const sorted = messages.sort((a, b) => b.timestamp - a.timestamp)
  return <div>{sorted.map(...)}</div>
}
```

### 减少内存占用

**流式处理**:
```python
# ✅ 好的做法（流式处理）
async def process_large_file(self, file_path: str):
    with open(file_path, "rb") as f:
        while chunk := f.read(4096):
            await self.process_chunk(chunk)

# ❌ 不好的做法（一次性加载）
async def process_large_file(self, file_path: str):
    with open(file_path, "rb") as f:
        data = f.read()  # 可能占用大量内存
    return await self.process_chunk(data)
```

**及时清理资源**:
```python
# ✅ 好的做法
class ConversationOrchestrator:
    async def close(self):
        """清理资源"""
        await self.input_pipeline.close()
        await self.output_pipeline.close()
        await self.agent.close()

# ❌ 不好的做法（无清理）
class ConversationOrchestrator:
    # 资源永不释放，导致内存泄漏
    pass
```

### 批量操作

**批量发送事件**:
```python
# ✅ 好的做法（批量发送）
async def emit_batch_events(self, events: List[OutputEvent]):
    """批量发送事件"""
    tasks = [self.event_bus.emit(event) for event in events]
    await asyncio.gather(*tasks)

# ❌ 不好的做法（逐个发送）
async def emit_events(self, events: List[OutputEvent]):
    for event in events:
        await self.event_bus.emit(event)  # 串行发送
```

---

## 测试策略

### 单元测试

**使用 pytest**:
```python
# ✅ 好的做法
import pytest
from anima.services.llm.base import LLMInterface

class TestLLMService:
    @pytest.fixture
    def agent(self):
        return MockLLMAgent()

    @pytest.mark.asyncio
    async def test_chat_stream(self, agent):
        """测试流式对话"""
        chunks = []
        async for chunk in agent.chat_stream("你好"):
            chunks.append(chunk)

        assert len(chunks) > 0
        assert "".join(chunks) == "你好！"

    def test_close(self, agent):
        """测试关闭连接"""
        agent.close()
        assert agent.client is None

# ❌ 不好的做法（无测试）
class LLMService:
    pass  # 没有测试
```

### 集成测试

**使用 TestClient**:
```python
# ✅ 好的做法
from fastapi.testclient import TestClient
from anima.socketio_server import app

client = TestClient(app)

def test_websocket_connection():
    """测试 WebSocket 连接"""
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "connect"})
        data = websocket.receive_json()
        assert data["type"] == "connection-established"

# ❌ 不好的做法（手动测试）
# 每次都手动启动服务器并手动测试
```

### 端到端测试

**使用 Playwright**:
```typescript
// ✅ 好的做法
import { test, expect } from '@playwright/test'

test('发送消息', async ({ page }) => {
  await page.goto('http://localhost:3000')

  await page.fill('[data-testid="input-box"]', '你好')
  await page.click('[data-testid="send-button"]')

  await expect(page.locator('[data-testid="message-list"]')).toContainText('你好')
})

// ❌ 不好的做法（手动测试）
// 每次都手动打开浏览器并测试
```

---

## 总结

### 最佳实践速查表

| 方面 | ✅ 好的做法 | ❌ 不好的做法 |
|------|------------|--------------|
| **代码风格** | 遵循 PEP 8，使用类型注解 | 命名混乱，无类型 |
| **异步编程** | 始终使用 async/await | 阻塞调用 |
| **错误处理** | 具体异常捕获，保留链 | 捕获所有异常 |
| **性能优化** | 使用缓存，流式处理 | 重复计算，一次性加载 |
| **测试** | 单元测试 + 集成测试 | 无测试 |

### 核心原则

1. **类型安全**: Python 和 TypeScript 都使用类型注解
2. **异步优先**: 所有 I/O 操作都使用 async/await
3. **错误处理**: 具体异常捕获，保留原始错误信息
4. **性能优化**: 缓存、流式处理、批量操作
5. **测试覆盖**: 单元测试、集成测试、端到端测试

---

**最后更新**: 2026-02-28

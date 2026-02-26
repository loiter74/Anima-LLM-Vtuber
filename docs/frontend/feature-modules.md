# 特性模块

## 概述

Anima 前端采用**基于特性的架构**，其中每个特性都是一个独立的模块，拥有自己的 hooks、服务和类型。这促进了代码组织、可重用性和可维护性。

## 特性结构

每个特性遵循以下结构：

```
features/
└── [feature-name]/
    ├── hooks/
    │   ├── index.ts           # 桶导出
    │   └── use[Feature].ts    # 自定义 React hooks
    └── services/
        ├── index.ts           # 桶导出
        └── [Service].ts       # 服务类
```

---

## 音频特性

**位置**: `features/audio/`

### 用途

处理所有音频相关功能：
- 麦克风录音
- 从 base64 播放音频
- 语音活动检测（VAD）处理

### 服务

#### AudioRecorder

**文件**: `services/AudioRecorder.ts`

**用途**: 从麦克风录制音频并流式传输 PCM 数据

**主要功能**:
- Web Audio API 集成
- Float32 到 Int16 PCM 转换
- 可配置的增益放大
- 带用户友好错误的权限处理
- 基于回调的分块流式传输

**使用方法**:
```typescript
import { AudioRecorder } from '@/features/audio/services'

const recorder = new AudioRecorder({
  sampleRate: 16000,
  channelCount: 1,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
  gain: 50.0,
})

await recorder.start((pcmData: Int16Array) => {
  // 处理 PCM 音频块
  sendToBackend(pcmData)
})

recorder.stop()
```

**配置选项**:
- `sampleRate`: 音频采样率（默认: 16000 Hz，与后端兼容）
- `channelCount`: 音频通道数（默认: 1，单声道）
- `echoCancellation`: 启用回声消除（默认: false）
- `noiseSuppression`: 启用降噪（默认: false）
- `autoGainControl`: 启用自动增益控制（默认: false）
- `gain`: 音频增益倍数（默认: 50.0）

---

#### AudioPlayer

**文件**: `services/AudioPlayer.ts`

**用途**: 从 base64 编码数据播放音频

**主要功能**:
- 从魔术字节自动检测 MIME 类型
- 数据 URI 方法以获得更好的浏览器兼容性
- 事件生命周期（onPlayStart、onPlayEnd、onError）
- 全局音频中断机制
- 详细的错误日志

**使用方法**:
```typescript
import { AudioPlayer } from '@/features/audio/services'

const player = new AudioPlayer({
  onPlayStart: () => console.log('Started'),
  onPlayEnd: () => console.log('Ended'),
  onError: (err) => console.error(err),
})

await player.play(base64AudioData, 'mp3')

player.stop()

// 全局中断的静态方法
AudioPlayer.stopGlobalAudio()
```

**支持的格式**:
- MP3 (audio/mpeg)
- WAV (audio/wav)
- OGG (audio/ogg)
- WebM (audio/webm)
- FLAC (audio/flac)
- AAC (audio/aac)
- M4A/MP4 (audio/mp4)

---

#### VADProcessor

**文件**: `services/VADProcessor.ts`

**用途**: 语音活动检测，用于自动检测语音结束

**主要功能**:
- Silero VAD 模型集成
- 可配置的灵敏度
- 自动检测语音结束以触发 ASR
- 15 秒安全超时

**使用方法**:
```typescript
import { VADProcessor } from '@/features/audio/services'

const vad = new VADProcessor({
  probThreshold: 0.8,
  dbThreshold: 40,
  requiredHits: 8,
  requiredMisses: 20,
})

vad.on('speech_start', () => {
  console.log('Speech detected')
})

vad.on('speech_end', () => {
  console.log('Speech ended - trigger ASR')
})

vad.process(audioChunk)
```

---

### Hooks

#### useAudioRecorder

**文件**: `hooks/useAudioRecorder.ts`

**用途**: 音频录制的 React hook

**返回值**:
- `recording`: 布尔值，指示是否正在录音
- `startRecording(onData)`: 开始录音
- `stopRecording()`: 停止录音
- `error`: 错误信息（如果有）

**使用方法**:
```typescript
import { useAudioRecorder } from '@/features/audio/hooks'

function MicrophoneButton() {
  const { recording, startRecording, stopRecording } = useAudioRecorder()

  return (
    <Button onClick={recording ? stopRecording : startRecording}>
      {recording ? 'Stop' : 'Start'}
    </Button>
  )
}
```

---

#### useAudioPlayer

**文件**: `hooks/useAudioPlayer.ts`

**用途**: 音频播放的 React hook

**返回值**:
- `play(base64, format)`: 播放音频
- `stop()`: 停止播放
- `state`: 播放器状态（'idle'、'playing'、'stopped'、'error'）

**使用方法**:
```typescript
import { useAudioPlayer } from '@/features/audio/hooks'

function AudioHandler({ audioData }) {
  const { play, state } = useAudioPlayer()

  useEffect(() => {
    if (audioData && state === 'idle') {
      play(audioData, 'mp3')
    }
  }, [audioData])

  return <div>State: {state}</div>
}
```

---

## 连接特性

**位置**: `features/connection/`

### 用途

管理与后端服务器的 Socket.IO 连接

### 服务

#### SocketClient

**文件**: `services/SocketClient.ts`

**用途**: 底层 Socket.IO 客户端包装器

**主要功能**:
- 类型安全的事件处理
- 带指数退避的自动重连
- 传输方式回退（websocket → polling）
- 30 秒连接超时
- 详细的日志记录

**使用方法**:
```typescript
import { SocketClient } from '@/features/connection/services'

const client = new SocketClient('http://localhost:12394')

await client.connect()

client.on('text', (data) => {
  console.log('Received:', data)
})

client.emit('text_input', { text: 'Hello' })

client.disconnect()
```

---

#### SocketService

**文件**: `services/SocketService.ts`

**用途**: 带应用逻辑的高层 Socket.IO 服务

**主要功能**:
- 在 Zustand store 中管理连接状态
- 内置事件处理器（连接、控制、错误）
- 每个事件可注册多个处理器
- 断开连接时自动清理

**内置处理器**:
- `connection-established`: 记录连接成功
- `control`: 根据控制信号更新连接状态
- `error`: 更新错误状态并转发给处理器

**使用方法**:
```typescript
import { SocketService } from '@/features/connection/services'

const socket = new SocketService()

await socket.connect()

// 注册自定义处理器
socket.on('text', (data) => {
  console.log('Text:', data.text)
})

// 移除处理器
socket.off('text', handler)

// 发送事件
socket.emit('text_input', { text: 'Hello' })

// 断开连接
socket.disconnect()
```

**处理的控制信号**:
- `START_MIC`: 将状态设置为 'connected'
- `INTERRUPT`、`INTERRUPTED`: 将状态设置为 'disconnected'
- `NO_AUDIO_DATA`、`CONVERSATION_END`: 将状态设置为 'connected'
- `CONVERSATION_START`、`MIC_AUDIO_END`: 将状态设置为 'connected'

---

### Hooks

#### useSocket

**文件**: `hooks/useSocket.ts`

**用途**: Socket.IO 连接的 React hook

**返回值**:
- `socket`: SocketService 实例
- `connect()`: 连接到服务器
- `disconnect()`: 从服务器断开连接
- `connected`: 布尔值连接状态

**使用方法**:
```typescript
import { useSocket } from '@/features/connection/hooks'

function ConnectionManager() {
  const { socket, connected, connect, disconnect } = useSocket()

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [])

  return <div>Status: {connected ? 'Connected' : 'Disconnected'}</div>
}
```

---

## 对话特性

**位置**: `features/conversation/`

### 用途

管理对话状态和消息处理

### Hooks

#### useConversation

**文件**: `hooks/useConversation.ts`

**用途**: 主要的对话管理 hook

**返回值**:
- `messages`: 对话消息数组
- `status`: 当前对话状态
- `currentText`: 流式响应文本
- `sendText(text)`: 发送文本消息
- `interrupt()`: 中断当前响应
- `clear()`: 清除对话历史

**使用方法**:
```typescript
import { useConversation } from '@/features/conversation/hooks'

function ChatInterface() {
  const { messages, status, sendText, interrupt } = useConversation()

  return (
    <div>
      {messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}
      {status === 'processing' && (
        <Button onClick={interrupt}>Interrupt</Button>
      )}
    </div>
  )
}
```

**状态值**:
- `idle`: 未在处理
- `listening`: 正在监听麦克风输入
- `processing`: 正在处理用户输入
- `speaking`: AI 正在说话
- `interrupted`: 响应被中断
- `error`: 发生错误

---

## 特性隔离模式

### 1. 桶导出

每个特性使用桶导出（`index.ts`）来实现清晰的导入：

```typescript
// features/audio/hooks/index.ts
export { useAudioPlayer } from './useAudioPlayer'
export { useAudioRecorder } from './useAudioRecorder'

// 使用
import { useAudioPlayer, useAudioRecorder } from '@/features/audio/hooks'
```

### 2. 特性类型

特性模块共享的类型放在 `shared/types/` 中：

```typescript
// shared/types/audio.ts
export interface AudioRecorderOptions {
  sampleRate?: number
  channelCount?: number
  // ...
}

// 在特性中使用
import type { AudioRecorderOptions } from '@/shared/types/audio'
```

### 3. 特性状态

全局状态在 Zustand stores 中管理：

```typescript
// shared/state/stores/audioStore.ts
import { create } from 'zustand'

export const useAudioStore = create<AudioState>((set) => ({
  isRecording: false,
  isPlaying: false,
  setRecording: (val) => set({ isRecording: val }),
  // ...
}))

// 在特性 hook 中使用
import { useAudioStore } from '@/shared/state/stores'
```

### 4. 特性常量

特性使用的常量放在 `shared/constants/` 中：

```typescript
// shared/constants/events.ts
export const CONTROL_SIGNALS = {
  START_MIC: 'start-mic',
  STOP_MIC: 'stop-mic',
  INTERRUPT: 'interrupt',
} as const

// 在特性中使用
import { CONTROL_SIGNALS } from '@/shared/constants/events'
```

---

## 添加新特性

### 步骤 1: 创建特性目录

```bash
mkdir -p features/my-feature/{hooks,services}
```

### 步骤 2: 创建服务

```typescript
// features/my-feature/services/MyService.ts
export class MyService {
  constructor(config?: Config) {
    // 初始化
  }

  async doSomething(): Promise<void> {
    // 实现
  }
}
```

### 步骤 3: 创建 Hook

```typescript
// features/my-feature/hooks/useMyFeature.ts
import { MyService } from '../services'

export function useMyFeature() {
  const [service] = useState(() => new MyService())

  const doSomething = useCallback(async () => {
    await service.doSomething()
  }, [service])

  return { doSomething }
}
```

### 步骤 4: 创建桶导出

```typescript
// features/my-feature/services/index.ts
export { MyService } from './MyService'

// features/my-feature/hooks/index.ts
export { useMyFeature } from './useMyFeature'

// features/my-feature/index.ts
export * from './hooks'
export * from './services'
```

### 步骤 5: 添加类型（如果需要）

```typescript
// shared/types/my-feature.ts
export interface MyFeatureConfig {
  // ...
}
```

### 步骤 6: 添加状态 Store（如果需要）

```typescript
// shared/state/stores/myFeatureStore.ts
import { create } from 'zustand'

export const useMyFeatureStore = create<MyFeatureState>((set) => ({
  // ...
}))
```

### 步骤 7: 在组件中使用

```typescript
import { useMyFeature } from '@/features/my-feature'

function MyComponent() {
  const { doSomething } = useMyFeature()
  return <Button onClick={doSomething}>Do Something</Button>
}
```

---

## 特性通信

### 通过 Socket.IO

特性通过 Socket.IO 进行通信，使用连接特性：

```typescript
// 音频特性发送数据
socket.emit('raw_audio_data', { audio: pcmData })

// 对话特性接收文本
socket.on('text', (data) => {
  addMessage({ role: 'assistant', content: data.text })
})
```

### 通过状态 Stores

特性通过 Zustand stores 共享状态：

```typescript
// 音频特性更新状态
useAudioStore.getState().setRecording(true)

// 对话特性读取状态
const isRecording = useAudioStore((s) => s.isRecording)
```

### 通过 Props

直接的父子通信：

```typescript
// 父组件传递处理器给子组件
<MicrophoneButton onRecordingChange={setIsRecording} />
```

---

## 测试特性

### 单元测试服务

```typescript
import { AudioRecorder } from '@/features/audio/services'

describe('AudioRecorder', () => {
  it('should start recording', async () => {
    const recorder = new AudioRecorder()
    const callback = vi.fn()
    await recorder.start(callback)
    expect(recorder.recording).toBe(true)
  })
})
```

### 集成测试 Hooks

```typescript
import { renderHook, act } from '@testing-library/react'
import { useAudioRecorder } from '@/features/audio/hooks'

describe('useAudioRecorder', () => {
  it('should start recording', async () => {
    const { result } = renderHook(() => useAudioRecorder())
    await act(async () => {
      await result.current.startRecording(vi.fn())
    })
    expect(result.current.recording).toBe(true)
  })
})
```

---

## 最佳实践

### 1. 保持服务独立

服务不应依赖 React。它们应该是纯 TypeScript 类：

```typescript
// 好
export class AudioRecorder {
  start() { /* 纯逻辑 */ }
}

// 避免
export class AudioRecorder {
  start() {
    const setState = useState()[1]  // 不要在服务中使用 React hooks
  }
}
```

### 2. 使用 Hooks 进行 React 集成

Hooks 桥接服务和 React 组件：

```typescript
export function useAudioRecorder() {
  const [recording, setRecording] = useState(false)
  const service = useMemo(() => new AudioRecorder(), [])

  const start = useCallback(async () => {
    await service.start()
    setRecording(true)
  }, [service])

  return { recording, start }
}
```

### 3. 处理清理

始终在 hooks 中清理资源：

```typescript
useEffect(() => {
  const recorder = new AudioRecorder()
  recorder.start(callback)

  return () => {
    recorder.stop()  // 清理
  }
}, [])
```

### 4. 错误边界

在错误边界中包装特性：

```typescript
<ErrorBoundary fallback={<ErrorDisplay />}>
  <AudioFeature />
</ErrorBoundary>
```

### 5. 类型安全

始终为 props 和服务方法添加类型：

```typescript
interface AudioRecorderOptions {
  sampleRate: number
  channelCount: number
}

export class AudioRecorder {
  constructor(options: AudioRecorderOptions) {
    // ...
  }
}
```

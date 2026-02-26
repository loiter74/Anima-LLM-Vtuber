# API 参考文档

## 概述

本参考文档详细记录了 Anima 前端中使用的所有自定义 hooks、服务、状态存储和类型定义。

## 目录

- [自定义 Hooks](#自定义-hooks)
- [服务](#服务)
- [状态存储](#状态存储)
- [类型定义](#类型定义)
- [常量](#常量)

---

## 自定义 Hooks

### useConversation

**导入路径**: `@/features/conversation/hooks`

**用于管理对话状态和消息的 Hook。**

#### 返回值

```typescript
interface UseConversationReturn {
  // 状态
  messages: Message[]
  status: ConversationStatus
  currentText: string

  // 操作方法
  sendText: (text: string) => Promise<void>
  interrupt: () => void
  clear: () => void

  // 计算属性
  isProcessing: boolean
  canInterrupt: boolean
}
```

#### 使用示例

```typescript
import { useConversation } from '@/features/conversation/hooks'

function Chat() {
  const {
    messages,
    status,
    sendText,
    interrupt,
    canInterrupt
  } = useConversation()

  return (
    <div>
      {messages.map(msg => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {canInterrupt && (
        <Button onClick={interrupt}>停止</Button>
      )}
    </div>
  )
}
```

---

### useAudioRecorder

**导入路径**: `@/features/audio/hooks`

**用于从麦克风录制音频的 Hook。**

#### 返回值

```typescript
interface UseAudioRecorderReturn {
  recording: boolean
  startRecording: (onData: (pcmData: Int16Array) => void) => Promise<void>
  stopRecording: () => void
  error: string | null
}
```

#### 使用示例

```typescript
import { useAudioRecorder } from '@/features/audio/hooks'

function MicButton() {
  const { recording, startRecording, stopRecording, error } = useAudioRecorder()

  const handleToggle = async () => {
    if (recording) {
      stopRecording()
    } else {
      await startRecording((data) => {
        socket.emit('raw_audio_data', { audio: Array.from(data) })
      })
    }
  }

  return (
    <div>
      <Button onClick={handleToggle}>
        {recording ? '停止' : '录制'}
      </Button>
      {error && <ErrorMessage>{error}</ErrorMessage>}
    </div>
  )
}
```

---

### useAudioPlayer

**导入路径**: `@/features/audio/hooks`

**用于播放 base64 音频数据的 Hook。**

#### 返回值

```typescript
interface UseAudioPlayerReturn {
  play: (base64Data: string, format?: string) => Promise<void>
  stop: () => void
  state: AudioPlayerState
  error: Error | null
}

type AudioPlayerState = 'idle' | 'playing' | 'stopped' | 'error'
```

#### 使用示例

```typescript
import { useAudioPlayer } from '@/features/audio/hooks'

function AudioHandler({ base64Audio }) {
  const { play, state } = useAudioPlayer()

  useEffect(() => {
    if (base64Audio && state === 'idle') {
      play(base64Audio, 'mp3')
    }
  }, [base64Audio])

  return <div>播放器状态: {state}</div>
}
```

---

### useSocket

**导入路径**: `@/features/connection/hooks`

**用于管理 Socket.IO 连接的 Hook。**

#### 返回值

```typescript
interface UseSocketReturn {
  socket: SocketService | null
  connected: boolean
  connect: () => Promise<void>
  disconnect: () => void
  sessionId: string | null
}
```

#### 使用示例

```typescript
import { useSocket } from '@/features/connection/hooks'

function ConnectionManager() {
  const { socket, connected, connect, disconnect } = useSocket()

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [])

  return <div>状态: {connected ? '已连接' : '未连接'}</div>
}
```

---

### useMobile

**导入路径**: `@/components/ui/use-mobile`

**用于检测移动设备屏幕尺寸的 Hook。**

#### 返回值

```typescript
boolean // 当屏幕宽度 < 768px 时返回 true
```

#### 使用示例

```typescript
import { useMobile } from '@/components/ui/use-mobile'

function ResponsiveComponent() {
  const isMobile = useMobile()
  return isMobile ? <MobileLayout /> : <DesktopLayout />
}
```

---

### useToast

**导入路径**: `@/components/ui/use-toast`

**用于显示 toast 通知的 Hook。**

#### 返回值

```typescript
interface UseToastReturn {
  toast: (props: ToastProps) => void
  toasts: Toast[]
  dismiss: (toastId: string) => void
}

interface ToastProps {
  title?: string
  description?: string
  variant?: 'default' | 'destructive'
  duration?: number
}
```

#### 使用示例

```typescript
import { useToast } from '@/components/ui/use-toast'

function SaveButton() {
  const { toast } = useToast()

  const handleSave = async () => {
    try {
      await saveData()
      toast({
        title: '成功',
        description: '设置已保存',
      })
    } catch (err) {
      toast({
        title: '错误',
        description: err.message,
        variant: 'destructive',
      })
    }
  }
}
```

---

## 服务

### SocketService

**导入路径**: `@/features/connection/services`

**带有应用逻辑的高级 Socket.IO 服务。**

#### 构造函数

```typescript
constructor(url?: string)
```

#### 方法

##### connect()

```typescript
async connect(): Promise<void>
```

连接到 Socket.IO 服务器。更新连接存储状态。

**可能抛出**: 连接超时或错误

---

##### disconnect()

```typescript
disconnect(): void
```

断开与服务器的连接并清除所有处理器。

---

##### on()

```typescript
on<Event extends keyof SocketEvents>(
  event: Event,
  callback: SocketEvents[Event]
): void
```

注册事件监听器。可以为同一事件注册多个处理器。

---

##### off()

```typescript
off<Event extends keyof SocketEvents>(
  event: Event,
  callback?: SocketEvents[Event]
): void
```

取消注册事件监听器。如果未提供回调函数，则清除该事件的所有处理器。

---

##### emit()

```typescript
emit<Event extends keyof SocketEmits>(
  event: Event,
  ...args: Parameters<SocketEmits[Event]>
): void
```

向服务器发送事件。

---

#### 属性

```typescript
id: string | undefined  // Socket ID
connected: boolean      // 连接状态
raw: SocketClient       // 底层 SocketClient
```

---

### SocketClient

**导入路径**: `@/features/connection/services`

**底层 Socket.IO 客户端封装。**

#### 构造函数

```typescript
constructor(url: string = DEFAULT_SERVER_URL)
```

#### 方法

##### connect()

```typescript
connect(): Promise<void>
```

建立 WebSocket 连接，超时时间为 30 秒。

---

##### disconnect()

```typescript
disconnect(): void
```

关闭 Socket 连接。

---

##### on()

```typescript
on<Event extends keyof SocketEvents>(
  event: Event,
  callback: SocketEvents[Event]
): void
```

注册事件监听器。

---

##### off()

```typescript
off<Event extends keyof SocketEvents>(
  event: Event,
  callback?: SocketEvents[Event]
): void
```

取消注册事件监听器。

---

##### emit()

```typescript
emit<Event extends keyof SocketEmits>(
  event: Event,
  ...args: Parameters<SocketEmits[Event]>
): void
```

向服务器发送事件。

---

#### 属性

```typescript
id: string | undefined   // Socket ID
connected: boolean       // 连接状态
raw: Socket | null       // 原始 socket.io Socket 实例
```

---

### AudioRecorder

**导入路径**: `@/features/audio/services`

**使用 Web Audio API 的音频录制服务。**

#### 构造函数

```typescript
constructor(options?: AudioRecorderOptions)

interface AudioRecorderOptions {
  sampleRate?: number         // 默认: 16000
  channelCount?: number       // 默认: 1
  echoCancellation?: boolean  // 默认: false
  noiseSuppression?: boolean  // 默认: false
  autoGainControl?: boolean   // 默认: false
  gain?: number              // 默认: 50.0
}
```

#### 方法

##### start()

```typescript
async start(onAudioData: (pcmData: Int16Array) => void): Promise<void>
```

开始录制音频。回调函数接收 Int16Array 格式的 PCM 数据块。

**可能抛出**: 权限被拒绝、未找到设备等错误

---

##### stop()

```typescript
stop(): void
```

停止录制并清理资源。

---

#### 属性

```typescript
recording: boolean  // 录制状态
```

---

### AudioPlayer

**导入路径**: `@/features/audio/services`

**带有格式检测的音频播放服务。**

#### 构造函数

```typescript
constructor(options?: AudioPlayerOptions)

interface AudioPlayerOptions {
  onPlayStart?: () => void
  onPlayEnd?: () => void
  onError?: (error: Error) => void
}
```

#### 方法

##### play()

```typescript
async play(base64Data: string, format?: string): Promise<void>
```

播放 base64 字符串格式的音频。格式提示可选（自动检测）。

**可能抛出**: 无效数据、不支持的格式

---

##### stop()

```typescript
stop(): void
```

停止当前播放。

---

##### destroy()

```typescript
destroy(): void
```

清理资源。

---

##### stopGlobalAudio()

```typescript
static stopGlobalAudio(): void
```

全局停止正在播放的音频（用于中断处理）。

---

#### 属性

```typescript
currentState: AudioPlayerState
isPlaying: boolean

type AudioPlayerState = 'idle' | 'playing' | 'stopped' | 'error'
```

---

### VADProcessor

**导入路径**: `@/features/audio/services`

**使用 Silero VAD 模型的语音活动检测。**

#### 构造函数

```typescript
constructor(options?: VADOptions)

interface VADOptions {
  probThreshold?: number    // 默认: 0.8
  dbThreshold?: number      // 默认: 40
  requiredHits?: number     // 默认: 8
  requiredMisses?: number   // 默认: 20
}
```

#### 方法

##### process()

```typescript
process(audioData: Float32Array): boolean
```

处理音频数据块并返回 VAD 结果。

---

##### on()

```typescript
on(event: 'speech_start' | 'speech_end', callback: () => void): void
```

注册 VAD 事件监听器。

---

#### 事件

- `speech_start`: 检测到语音
- `speech_end`: 语音结束（触发 ASR）

---

## 状态存储

### useConversationStore

**导入路径**: `@/shared/state/stores`

**对话状态管理。**

#### 状态

```typescript
interface ConversationState {
  messages: Message[]
  status: ConversationStatus
  currentText: string
  audioQueue: string[]

  // 操作方法
  addMessage: (message: Message) => void
  setStatus: (status: ConversationStatus) => void
  setCurrentText: (text: string) => void
  clearMessages: () => void
  enqueueAudio: (base64: string) => void
  dequeueAudio: () => string | undefined
}
```

#### 使用示例

```typescript
import { useConversationStore } from '@/shared/state/stores'

function Chat() {
  const messages = useConversationStore((s) => s.messages)
  const addMessage = useConversationStore((s) => s.addMessage)

  return <div>{/* ... */}</div>
}
```

---

### useConnectionStore

**导入路径**: `@/shared/state/stores`

**连接状态管理。**

#### 状态

```typescript
interface ConnectionState {
  status: ConnectionStatus
  sessionId: string | null
  error: string | null

  // 操作方法
  setStatus: (status: ConnectionStatus) => void
  setSessionId: (id: string | null) => void
  setError: (error: string | null) => void
}

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'
```

#### 使用示例

```typescript
import { useConnectionStore } from '@/shared/state/stores'

function ConnectionStatus() {
  const status = useConnectionStore((s) => s.status)
  return <Badge>{status}</Badge>
}
```

---

### useAudioStore

**导入路径**: `@/shared/state/stores`

**音频状态管理。**

#### 状态

```typescript
interface AudioState {
  isRecording: boolean
  isPlaying: boolean
  vadEnabled: boolean
  vadThreshold: number

  // 操作方法
  setRecording: (recording: boolean) => void
  setPlaying: (playing: boolean) => void
  setVadEnabled: (enabled: boolean) => void
  setVadThreshold: (threshold: number) => void
}
```

#### 使用示例

```typescript
import { useAudioStore } from '@/shared/state/stores'

function MicButton() {
  const isRecording = useAudioStore((s) => s.isRecording)
  const setRecording = useAudioStore((s) => s.setRecording)

  return <Button onClick={() => setRecording(!isRecording)} />
}
```

---

## 类型定义

### 消息类型

**导入路径**: `@/shared/types/conversation`

```typescript
interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  metadata?: Record<string, unknown>
}
```

---

### 对话状态

**导入路径**: `@/shared/types/conversation`

```typescript
type ConversationStatus =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking'
  | 'interrupted'
  | 'error'
```

---

### Socket 事件

**导入路径**: `@/shared/types/socket`

```typescript
interface SocketEvents {
  'connection-established': { message: string }
  'text': TextData
  'audio': AudioData
  'transcript': TranscriptData
  'control': ControlData
  'error': ErrorData
}

interface TextData {
  text: string
  seq?: number
  metadata?: Record<string, unknown>
}

interface AudioData {
  audio: string
  format?: string
  seq?: number
}

interface TranscriptData {
  text: string
  is_final: boolean
}

interface ControlData {
  text: string
  metadata?: Record<string, unknown>
}

interface ErrorData {
  message: string
  code?: string
}
```

---

### Socket 发送事件

**导入路径**: `@/shared/types/socket`

```typescript
interface SocketEmits {
  'text_input': TextInputData
  'mic_audio_data': AudioInputData
  'raw_audio_data': RawAudioData
  'mic_audio_end': AudioEndData
  'interrupt_signal': InterruptData
}

interface TextInputData {
  text: string
  metadata?: Record<string, unknown>
  from_name?: string
}

interface AudioInputData {
  audio: number[]
  sample_rate?: number
}

interface RawAudioData {
  audio: number[]
  metadata?: Record<string, unknown>
}

interface AudioEndData {
  metadata?: Record<string, unknown>
}

interface InterruptData {
  metadata?: Record<string, unknown>
}
```

---

### 音频类型

**导入路径**: `@/shared/types/audio`

```typescript
interface AudioRecorderOptions {
  sampleRate?: number
  channelCount?: number
  echoCancellation?: boolean
  noiseSuppression?: boolean
  autoGainControl?: boolean
  gain?: number
}

interface AudioPlayerOptions {
  onPlayStart?: () => void
  onPlayEnd?: () => void
  onError?: (error: Error) => void
}

type AudioPlayerState = 'idle' | 'playing' | 'stopped' | 'error'

type AudioDataCallback = (pcmData: Int16Array) => void
```

---

## 常量

### 控制信号

**导入路径**: `@/shared/constants/events`

```typescript
export const CONTROL_SIGNALS = {
  START_MIC: 'start-mic',
  STOP_MIC: 'stop-mic',
  INTERRUPT: 'interrupt',
  INTERRUPTED: 'interrupted',
  NO_AUDIO_DATA: 'no-audio-data',
  CONVERSATION_START: 'conversation-start',
  CONVERSATION_END: 'conversation-end',
  MIC_AUDIO_END: 'mic-audio-end',
} as const
```

---

### 状态样式

**导入路径**: `@/shared/constants/status`

```typescript
interface StatusStyle {
  bg: string      // Tailwind 背景类
  text: string    // Tailwind 文本类
  label: string   // 显示标签
}

export const STATUS_STYLES: Record<ConversationStatus, StatusStyle>
```

---

### 服务器配置

**导入路径**: `@/shared/constants/status`

```typescript
export const DEFAULT_SERVER_URL = "http://localhost:12394"
export const DEFAULT_SAMPLE_RATE = 16000
```

---

### 表情

**导入路径**: `@/shared/constants/status`

```typescript
interface Expression {
  name: string
  label: string
}

export const EXPRESSIONS: Expression[] = [
  { name: "Neutral", label: "Neutral" },
  { name: "Happy", label: "Happy" },
  { name: "Surprised", label: "Surprised" },
  { name: "Thinking", label: "Thinking" },
]
```

---

## 工具函数

### 格式化工具

**导入路径**: `@/shared/utils/format`

```typescript
// 将秒数格式化为 HH:MM:SS
function formatTime(seconds: number): string

// 获取当前时间，格式为 HH:MM
function getCurrentTime(): string

// 将时间戳格式化为 HH:MM
function formatTimestamp(timestamp: number): string

// 将日期格式化为 YYYY-MM-DD（重载）
function formatDate(date: Date): string
function formatDate(timestamp: number): string

// 将日期时间格式化为 YYYY-MM-DD HH:MM
function formatDateTime(timestamp: number): string

// 格式化数字，保留小数位
function formatNumber(num: number, decimals: number): string
```

---

### ID 生成

**导入路径**: `@/shared/utils/id`

```typescript
// 基于计数器的 ID，带时间戳
function generateId(prefix?: string): string

// 重置 ID 计数器
function resetIdCounter(): void

// 基于随机数的 ID
function generateRandomId(prefix?: string): string

// UUID v4
function generateUUID(): string
```

---

### 存储工具

**导入路径**: `@/shared/utils/storage`

```typescript
// 从 localStorage 获取值，带默认值
function getStorage<T>(key: string, defaultValue: T): T

// 设置到 localStorage
function setStorage<T>(key: string, value: T): void

// 从 localStorage 移除
function removeStorage(key: string): void
```

---

### 日志工具

**导入路径**: `@/shared/utils/logger`

```typescript
enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARN = 2,
  ERROR = 3,
  SILENT = 4
}

class Logger {
  setLevel(level: LogLevel): void
  getLevel(): LogLevel
  debug(message: string, ...args: unknown[]): void
  info(message: string, ...args: unknown[]): void
  warn(message: string, ...args: unknown[]): void
  error(message: string, ...args: unknown[]): void
}

export const logger: Logger
```

---

### 音频工具

**导入路径**: `@/shared/utils/audio`

```typescript
// 将 Float32Array 转换为 Int16Array
function float32ToInt16(data: Float32Array): Int16Array

// 将 base64 转换为 Blob
function base64ToBlob(base64: string, type: string): Blob

// 创建 blob URL
function blobToUrl(blob: Blob): string

// 撤销 blob URL
function revokeBlobUrl(url: string): void

// 对音频数据应用增益
function applyGain(data: Float32Array, gain: number): Float32Array
```

---

### 类名工具

**导入路径**: `@/shared/utils/cn`

```typescript
// 合并 Tailwind 类，具有正确的优先级
function cn(...inputs: ClassValue[]): string
```

**使用示例**:
```typescript
import { cn } from '@/shared/utils/cn'

<div className={cn('base-styles', isActive && 'active-styles', className)} />
```

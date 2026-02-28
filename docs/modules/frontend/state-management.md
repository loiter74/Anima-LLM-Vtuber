# 状态管理

> Zustand 的使用模式和最佳实践

---

## 目录

1. [Zustand 简介](#zustand-简介)
2. [Store 设计](#store-设计)
3. [Hook 封装](#hook-封装)
4. [最佳实践](#最佳实践)

---

## Zustand 简介

### 为什么选择 Zustand？

| 特性 | Zustand | Redux | Context API |
|------|--------|-------|-------------|
| **学习曲线** | ⭐ 简单 | ⭐⭐⭐ 陡峭 | ⭐⭐ 中等 |
| **样板代码** | ⭐⭐⭐ 极少 | ⭐ 大量 | ⭐⭐ 较多 |
| **性能** | ⭐⭐⭐⭐ 优秀 | ⭐⭐⭐ 良好 | ⭐⭐⭐ 一般 |
| **持久化** | ⭐⭐⭐ 中间件 | ⭐ 需要 Redux Persist | ⚠️ 需要 useState |
| **DevTools** | ⭐⭐⭐ 有 | ⭐⭐⭐⭐ 完善 | ⭐⭐⭐ 不支持 |

---

## Store 设计

### ConversationStore

```typescript
// frontend/shared/state/stores/conversationStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface Message {
  id: string
  role: 'user' | 'ai'
  content: string
  timestamp: number
}

interface ConversationState {
  // 状态
  messages: Message[]
  isConnected: boolean
  isTyping: boolean
  currentResponse: string

  // 计算属性（getters）
  lastMessageCount: number

  // 方法
  sendMessage: (text: string) => Promise<void>
  addMessage: (message: Message) => void
  clearMessages: () => void
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
    // ========== 状态 ==========
    messages: [],
    isConnected: false,
    isTyping: false,
    currentResponse: "",

    // ========== 计算属性 ==========
    get lastMessageCount(): number {
      return get().messages.filter(m => m.role === 'user').length
    },

    // ========== 方法 ==========
    sendMessage: async (text: string) => {
      const socketService = SocketService.getInstance()
      await socketService.send('text_input', { text })

      set({ isTyping: true })
    },

    addMessage: (message: Message) => {
      set((state) => ({
        messages: [...state.messages, message]
      }))
    },

    clearMessages: () => set({ messages: [] }),

    // ========== WebSocket 回调 ==========
    setIsConnected: (isConnected: boolean) => set({ isConnected }),
    appendResponse: (chunk: string) => set((state) => ({
      currentResponse: state.currentResponse + chunk
    })),
    finishResponse: () => set({ currentResponse: "", isTyping: false }),

    // ========== Action ==========
    addSystemMessage: (content: string) => {
      const message: Message = {
        id: Date.now().toString(),
        role: 'system',
        content,
        timestamp: Date.now()
      }
      set((state) => ({
        messages: [...state.messages, message]
      }))
    }
  }),
  {
    name: 'conversation-storage',
    partialize: (state) => ({
      messages: state.messages,
    }),
  }
)
```

### AudioStore

```typescript
// frontend/shared/state/stores/audioStore.ts
import { create } from 'zustand'

interface AudioState {
  // 状态
  isRecording: boolean
  isPlaying: boolean
  audioLevel: number
  currentAudioId: string | null

  // 方法
  startRecording: () => void
  stopRecording: () => void
  playAudio: (audioId: string) => void
  stopAudio: () => void
}

export const useAudioStore = create<AudioState>((set) => ({
  // ========== 状态 ==========
  isRecording: false,
  isPlaying: false,
  audioLevel: 0,
  currentAudioId: null,

  // ========== 方法 ==========
  startRecording: () => set({ isRecording: true }),
  stopRecording: () => set({ isRecording: false }),
  playAudio: (audioId) => set({ currentAudioId: audioId, isPlaying: true }),
  stopAudio: () => set({ currentAudioId: null, isPlaying: false }),

  // ========== AudioRecorder 回调 ==========
  setAudioLevel: (level: number) => set({ audioLevel: level }),
}))
```

### ConnectionStore

```typescript
// frontend/shared/state/stores/connectionStore.ts
import { create } from 'zustand'

interface ConnectionState {
  // 状态
  isConnected: boolean
  sessionId: string | null
  reconnectAttempts: number

  // 方法
  connect: () => void
  disconnect: () => void
  setSessionId: (sessionId: string) => void
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  // ========== 状态 ==========
  isConnected: false,
  sessionId: null,
  reconnectAttempts: 0,

  // ========== 方法 ==========
  connect: () => set({ isConnected: true }),
  disconnect: () => set({ isConnected: false, sessionId: null }),
  setSessionId: (sessionId: string) => set({ sessionId }),
  incrementReconnectAttempts: () => set((state) => ({
    reconnectAttempts: state.reconnectAttempts + 1
  })),
  resetReconnectAttempts: () => set({ reconnectAttempts: 0 }),
}))
```

---

## Hook 封装

### useConversation

```typescript
// frontend/features/conversation/hooks/useConversation.ts
import { useConversationStore } from '@/shared/state/stores/conversationStore'

export function useConversation() {
  const store = useConversationStore()

  return {
    // 只订阅特定字段（避免不必要的 re-render）
    messages: store.messages,
    isConnected: store.isConnected,
    isTyping: store.isTyping,

    // 方法
    sendMessage: store.sendMessage,
    clearMessages: store.clearMessages,
  }
}
```

### useAudioRecorder

```typescript
// frontend/features/audio/hooks/useAudioRecorder.ts
import { useAudioStore } from '@/shared/state/stores/audioStore'
import { AudioRecorder } from '../services/AudioRecorder'

export function useAudioRecorder() {
  const { isRecording, startRecording, stopRecording } = useAudioStore()

  const recorderRef = useRef<AudioRecorder | null>(null)

  const start = useCallback(() => {
    if (!recorderRef.current) {
      recorderRef.current = new AudioRecorder({
        onAudioLevel: (level) => {
          useAudioStore.getState().setAudioLevel(level)
        }
      })
    }
    recorderRef.current.start()
    startRecording()
  }, [])

  const stop = useCallback(() => {
    recorderRef.current?.stop()
    stopRecording()
  }, [])

  return {
    isRecording,
    start,
    stop,
  }
}
```

### useLive2D

```typescript
// frontend/features/live2d/hooks/useLive2D.ts
export function useLive2D(options: UseLive2DOptions) {
  const [isLoaded, setIsLoaded] = useState(false)
  const serviceRef = useRef<Live2DService | null>(null)

  const initService = useCallback(() => {
    const service = new Live2DService(canvasRef.current!, config)
    serviceRef.current = service

    service.on('model:loaded', () => setIsLoaded(true))
    service.loadModel()
  }, [config])

  const setExpression = useCallback((expression: string) => {
    serviceRef.current?.setExpression(expression)
  }, [])

  return {
    isLoaded,
    setExpression,
  }
}
```

---

## 最佳实践

### 1. 简化订阅

```typescript
// ✅ 好的做法：只订阅需要的字段
function ChatPanel() {
  const messages = useConversationStore(state => state.messages)
  const sendMessage = useConversationStore(state => state.sendMessage)

  return <div>{...}</div>
}

// ❌ 不好的做法：订阅整个 store
function ChatPanel() {
  const store = useConversationStore()
  return <div>{store.messages.map(...)}</div>
}
```

### 2. 拆分 Store

```typescript
// ✅ 好的做法：按功能拆分 Store
- conversationStore.ts   (对话消息)
- audioStore.ts          (音频状态)
- connectionStore.ts     (连接状态)

// ❌ 不好的做法：单个大 Store
- appStore.ts             (所有状态)
```

### 3. 使用持久化

```typescript
// ✅ 使用 persist 中间件
export const useStore = create(
  persist(
    (set, get) => ({
      messages: [],
      addMessage: (msg) => set(...)
    }),
    {
      name: 'storage-name',
      partialize: (state) => ({ messages: state.messages })
    }
  )
)
```

### 4. 避免 Context 包裹

```typescript
// ✅ 好的做法：直接使用 Hook
function ChatPanel() {
  const { messages, sendMessage } = useConversation()
  return <div>{...}</div>
}

// ❌ 不好的做法：额外包裹 Context
function ChatProvider({ children }) {
  return (
    <ConversationProvider>
      <ChatPanel />
    </ConversationProvider>
  )
}
```

---

## 总结

### Zustand 优势

1. **简洁**：代码量少，学习曲线平缓
2. **性能**：基于 React hooks，无额外开销
3. **类型安全**：TypeScript 类型推导优秀
4. **持久化**：内置中间件，简单易用

### Anima 使用经验

1. **按功能拆分 Store**：conversation, audio, connection
2. **直接使用 Hook**：移除 Context 冗余
3. **选择性订阅**：只订阅需要的字段
4. **persist 中间件**：自动保存到 localStorage

---

**最后更新**: 2026-02-28

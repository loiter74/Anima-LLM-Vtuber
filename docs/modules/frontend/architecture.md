# 前端架构

> Next.js + React + Zustand 的前端架构设计

---

## 目录

1. [架构概览](#架构概览)
2. [目录结构](#目录结构)
3. [数据流](#数据流)
4. [状态管理](#状态管理)
5. [组件模式](#组件模式)

---

## 架构概览

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Pages Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ app/page.tsx │  │ app/chat/page.tsx│  │ app/api/chat.│       │
│  │ (主页)        │  │ (聊天页面)    │  ts (API)     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      Features Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ conversation/ │  │ live2d/      │  │ audio/       │       │
│  │ 对话模块      │  │ Live2D 模块  │  │ 音频模块     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      Shared Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ state/        │  │ types/       │  │ utils/       │       │
│  │ stores.ts     │  │ index.ts     │  │ logger.ts    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                      UI Components                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ chat/         │  │ vtuber/      │  │ shared/      │       │
│  │ ChatPanel.tsx │  │ Live2DViewer │  │ ui/          │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
frontend/
├── app/                          # Next.js App Router
│   ├── page.tsx                  # 主页
│   ├── chat/
│   │   └── page.tsx              # 聊天页面
│   └── api/
│       ├── chat/
│       │   └── route.ts          # 聊天 API
│
├── features/                     # 功能模块
│   ├── conversation/            # 对话功能模块
│   │   ├── hooks/
│   │   │   └── useConversation.ts
│   │   ├── stores/
│   │   │   └── conversationStore.ts
│   │   └── services/
│   │       ├── SocketService.ts
│   │       └── AudioService.ts
│   │
│   ├── audio/                   # 音频功能模块
│   │   ├── hooks/
│   │   │   ├── useAudioRecorder.ts
│   │   │   └── useAudioPlayer.ts
│   │   └── services/
│   │       ├── AudioRecorder.ts
│   │       └── AudioPlayer.ts
│   │
│   └── live2d/                  # Live2D 功能模块
│       ├── hooks/
│       │   └── useLive2D.ts
│       ├── services/
│       │   ├── Live2DService.ts
│       │   ├── LipSyncEngine.ts
│       │   └── ExpressionTimeline.ts
│       └── types/
│           └── index.ts
│
├── components/                  # UI 组件
│   ├── vtuber/
│   │   ├── live2d-viewer.tsx
│   │   ├── chat-panel.tsx
│   │   └── bottom-toolbar.tsx
│   └── ui/                      # shadcn/ui 组件
│       └── ...
│
├── shared/                      # 共享代码
│   ├── state/
│   │   └── stores/
│   │       ├── conversationStore.ts
│   │       ├── audioStore.ts
│   │       └── connectionStore.ts
│   ├── types/
│   │   ├── index.ts
│   │   ├── conversation.ts
│   │   └── audio.ts
│   ├── utils/
│   │   ├── logger.ts
│   │   └── cn.ts
│   └── constants/
│       ├── events.ts
│       └── live2d.ts
│
└── public/                      # 静态资源
    ├── config/
    │   └── live2d.json
    └── live2d/               # Live2D 模型文件
        └── hiyori/
            ├── Hiyori.model3.json
            └── ...
```

---

## 数据流

### 客户端 → 服务器

```
用户操作 → UI 组件 → Hook → Store → SocketService → WebSocket
```

### 服务器 → 客户端

```
WebSocket → SocketService → Store → Hook → UI 组件 → 渲染
```

### 完整数据流

```
1. 用户输入文本
   ↓
2. ChatPanel.tsx 调用 useConversation.sendMessage()
   ↓
3. useConversation 调用 conversationStore.sendMessage()
   ↓
4. conversationStore 调用 SocketService.send('text_input')
   ↓
5. SocketService 通过 WebSocket 发送数据
   ↓
6. 后端处理并返回
   ↓
7. SocketService.on('text') 更新 conversationStore.messages
   ↓
8. useConversation 通过订阅获取最新 messages
   ↓
9. ChatPanel.tsx 渲染消息列表
```

---

## 状态管理

### Zustand Store 设计

```typescript
// frontend/shared/state/stores/conversationStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ConversationState {
  messages: Message[]
  isConnected: boolean
  isTyping: boolean
  sendMessage: (text: string) => Promise<void>
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      messages: [],
      isConnected: false,
      isTyping: false,

      sendMessage: async (text: string) => {
        const socketService = SocketService.getInstance()
        await socketService.send('text_input', { text })
        set({ isTyping: true })
      },

      addMessage: (message: Message) => {
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
)
```

### Hook 使用

```typescript
// frontend/features/conversation/hooks/useConversation.ts
export function useConversation() {
  const store = useConversationStore()

  return {
    // 直接返回 store（组件订阅特定字段）
    messages: store.messages,
    isConnected: store.isConnected,
    isTyping: store.isTyping,

    // 返回方法
    sendMessage: store.sendMessage,
  }
}
```

### 组件中使用

```typescript
// frontend/components/vtuber/chat-panel.tsx
import { useConversation } from '@/features/conversation/hooks/useConversation'

export function ChatPanel() {
  const { messages, sendMessage } = useConversation()

  return (
    <div>
      {messages.map(msg => (
        <div key={msg.id}>{msg.content}</div>
      ))}
      <button onClick={() => sendMessage("你好")}>
        发送
      </button>
    </div>
  )
}
```

---

## 组件模式

### Feature-based 模块

每个功能模块包含：

```
feature-name/
├── hooks/           # React Hooks
├── services/        # 服务层
├── stores/          # Zustand stores (如果需要)
├── types/           # TypeScript 类型
└── utils/           # 工具函数
```

### 示例：conversation 模块

```
conversation/
├── hooks/
│   └── useConversation.ts          # 对话 Hook
├── services/
│   ├── SocketService.ts           # WebSocket 服务
│   └── AudioService.ts            # 音频服务
└── stores/
    └── conversationStore.ts      # Zustand Store
```

---

## 总结

### 前端架构特点

1. **Feature-based**：按功能组织代码，易于维护
2. **No Context**：直接使用 Hooks，简化数据流
3. **Zustand**：轻量级状态管理，减少样板代码
4. **TypeScript**：100% 类型覆盖，提高代码质量

---

**最后更新**: 2026-02-28

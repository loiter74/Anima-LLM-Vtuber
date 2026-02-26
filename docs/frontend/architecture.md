# Anima 前端架构

## 概述

Anima 前端是一个基于 Next.js 16 的应用程序，使用 React 19、TypeScript 和 Socket.IO 与 AI 后端进行实时通信。应用采用基于特性的架构，包含共享工具和状态管理。

## 技术栈

- **框架**: Next.js 16 (App Router)
- **UI 库**: React 19 + TypeScript
- **实时通信**: Socket.IO Client
- **状态管理**: Zustand
- **样式**: Tailwind CSS
- **组件库**: shadcn/ui (Radix UI 原语 + Tailwind CSS)
- **包管理器**: pnpm

## 目录结构

```
frontend/
├── app/                    # Next.js App Router
│   ├── layout.tsx         # 根布局（包含 providers）
│   ├── page.tsx           # 主应用页面
│   └── globals.css        # 全局样式
│
├── components/             # 所有 React 组件
│   ├── ui/                # shadcn/ui 组件（16个组件）
│   ├── vtuber/            # VTuber 专用组件
│   └── layout/            # 布局组件
│
├── features/              # 基于特性的模块
│   ├── audio/            # 音频录制、播放、VAD
│   ├── connection/       # Socket.IO 连接管理
│   └── conversation/     # 聊天状态和消息处理
│
├── shared/               # 共享代码
│   ├── types/           # TypeScript 类型/接口
│   ├── state/stores/    # Zustand 状态存储
│   ├── constants/       # 应用常量
│   └── utils/           # 工具函数
│
├── contexts/            # React Context 提供者
└── styles/              # 全局样式
```

## 架构模式

### 1. 基于特性的架构

每个特性都是一个自包含的模块，拥有自己的：
- **Hooks**: 用于特性逻辑的自定义 React hooks
- **Services**: 业务逻辑和外部集成
- **Types**: 特定类型的类型定义

```
features/
├── audio/
│   ├── hooks/
│   │   ├── useAudioPlayer.ts
│   │   └── useAudioRecorder.ts
│   └── services/
│       ├── AudioPlayer.ts
│       ├── AudioRecorder.ts
│       └── VADProcessor.ts
```

### 2. 数据流

```
用户输入 → SocketService → 后端 Python
                ↓
          Socket 事件
                ↓
         事件处理器
                ↓
         状态存储 (Zustand)
                ↓
         React 组件（重新渲染）
```

### 3. 组件组合

```
app/page.tsx（主布局）
    ├── live-preview.tsx（视频/Live2D 显示）
    ├── chat-panel.tsx（聊天消息和输入）
    └── bottom-toolbar.tsx（控制和设置）
```

## 核心系统

### Socket.IO 通信

**服务层**:
- `SocketClient`: 底层 Socket.IO 封装
- `SocketService`: 带事件管理的高级服务

**连接流程**:
1. `SocketService.connect()` - 建立 WebSocket 连接
2. 内置处理器自动注册（连接、控制、错误事件）
3. 通过 `on(event, callback)` 注册自定义处理器
4. 通过 `emit(event, data)` 发送事件

**事件类型**:
- `connection-established`: 连接确认
- `text`: 文本响应块
- `audio`: 音频数据块
- `transcript`: 用户转录（ASR 结果）
- `control`: 控制信号（开始麦克风、停止麦克风、中断）
- `error`: 错误消息

### 音频处理

**AudioRecorder**（音频录制器）:
- 通过 Web Audio API 捕获麦克风输入
- 将 Float32 转换为 Int16 PCM 格式
- 应用可配置的增益放大
- 通过回调流式传输音频数据

**AudioPlayer**（音频播放器）:
- 从 base64 编码数据播放音频
- 从魔术字节自动检测 MIME 类型
- 管理音频元素生命周期
- 支持全局中断处理

**VADProcessor**（语音活动检测）:
- 语音活动检测集成
- 自动检测语音结束以触发 ASR
- 可配置的灵敏度阈值

### 状态管理

**Zustand 存储**:
- `connectionStore`: 连接状态、会话 ID、错误状态
- `conversationStore`: 消息、状态、当前文本、音频队列
- `audioStore`: 录制状态、播放状态、VAD 设置

**存储模式**:
```typescript
const useStore = create<Store>((set) => ({
  state: initialState,
  actions: {
    setState: (value) => set({ state: value }),
  },
}))
```

### 类型安全

**共享类型** (`shared/types/`):
- `audio.ts`: 音频录制/播放选项和回调
- `conversation.ts`: 消息类型、对话状态
- `socket.ts`: Socket.IO 事件和发送类型

## 组件模式

### UI 组件 (shadcn/ui)

所有 UI 组件遵循 shadcn/ui 模式：
- 组合优于配置
- 使用 Tailwind CSS 样式
- Radix UI 原语保证可访问性
- `cn()` 工具函数用于 className 合并

示例：
```typescript
import { Button } from '@/components/ui/button'
import { cn } from '@/shared/utils/cn'

<Button className={cn('base-styles', className)} />
```

### VTuber 组件

**chat-panel.tsx**（聊天面板）:
- 显示对话消息
- 处理文本输入
- 显示连接状态

**live-preview.tsx**（实时预览）:
- 视频/Live2D 模型显示
- 状态指示器徽章
- 表情控制

**bottom-toolbar.tsx**（底部工具栏）:
- 麦克风控制
- 音量/增益设置
- 连接管理
- 设置对话框

## 工具组织

**shared/utils/**:
- `audio.ts`: 音频处理工具
- `cn.ts`: Tailwind className 合并
- `format.ts`: 日期/时间/数字格式化
- `id.ts`: 唯一 ID 生成
- `logger.ts`: 前端日志系统
- `storage.ts`: LocalStorage 包装器

## 导入路径约定

```typescript
// UI 组件
import { Button } from '@/components/ui/button'

// 特性 hooks
import { useConversation } from '@/features/conversation/hooks'

// 特性服务
import { SocketService } from '@/features/connection/services'

// 共享工具
import { logger } from '@/shared/utils/logger'
import { cn } from '@/shared/utils/cn'

// 共享类型
import type { Message } from '@/shared/types/conversation'

// 共享存储
import { useConversationStore } from '@/shared/state/stores'
```

## 性能考虑

### React 优化
- 对昂贵的渲染进行组件记忆化
- 在 useEffect 中清理事件处理器
- 音频缓冲区回收

### 音频优化
- ScriptProcessorNode 用于实时音频（4096 缓冲区）
- 使用 Data URI 而非 blob URL 以获得更好的浏览器兼容性
- 全局音频中断机制

### 网络优化
- WebSocket 持久连接
- 指数退避自动重连
- 高频消息的事件批处理

## 开发工作流

### 添加新特性

1. 在 `features/` 下创建特性目录
2. 添加 `hooks/` 和 `services/` 子目录
3. 创建 index.ts 进行桶导出
4. 如有需要，在 `shared/types/` 中添加类型
5. 如果特性有状态，创建 Zustand 存储
6. 在组件中使用特性 hooks

### 添加新 UI 组件

1. 使用 shadcn/ui CLI: `pnpm dlx shadcn@latest add [component]`
2. 从 `@/shared/utils/cn` 导入工具
3. 遵循现有组件模式
4. 如果在其他地方使用，从 `components/ui/` 导出

## 测试策略

### 单元测试
- 测试 `shared/utils/` 中的工具函数
- 使用 render hooks 测试特性 hooks
- 使用模拟测试服务

### 集成测试
- 测试 Socket.IO 事件流
- 测试音频录制/播放管道
- 测试跨特性的状态更新

### 端到端测试
- 测试完整的对话流程
- 测试错误场景（连接丢失、权限拒绝）
- 测试音频中断行为

## 构建与部署

### 开发
```bash
pnpm dev          # 在 :3000 端口启动开发服务器
```

### 生产构建
```bash
pnpm build        # 创建优化的生产构建
pnpm start        # 启动生产服务器
```

### 环境变量
- `NEXT_PUBLIC_SOCKET_URL`: 后端 Socket.IO 服务器 URL（默认: http://localhost:12394）

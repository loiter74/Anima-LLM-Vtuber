# 组件使用指南

## 概述

本指南涵盖了 Anima 前端中使用的所有组件，包括 shadcn/ui 组件、VTuber 专用组件和布局组件。

## 目录

- [UI 组件 (shadcn/ui)](#ui-组件-shadcnui)
- [VTuber 组件](#vtuber-组件)
- [布局组件](#布局组件)
- [样式规范](#样式规范)

---

## UI 组件 (shadcn/ui)

我们使用 16 个 shadcn/ui 组件。所有组件位于 `components/ui/` 目录。

### Badge

**用途**: 显示状态指示器和标签

**用法**:
```typescript
import { Badge } from '@/components/ui/badge'

<Badge variant="default">Default</Badge>
<Badge variant="secondary">Secondary</Badge>
<Badge variant="outline">Outline</Badge>
<Badge variant="destructive">Destructive</Badge>
```

**代码库中的示例**:
- `live-preview.tsx` 中的连接状态指示器
- `chat-panel.tsx` 中的消息状态徽章

---

### Button

**用途**: 交互式按钮元素

**用法**:
```typescript
import { Button } from '@/components/ui/button'

<Button variant="default">Default</Button>
<Button variant="destructive">Destructive</Button>
<Button variant="outline">Outline</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="ghost">Ghost</Button>
<Button variant="link">Link</Button>
<Button size="sm">Small</Button>
<Button size="default">Default</Button>
<Button size="lg">Large</Button>
<Button size="icon">Icon</Button>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的麦克风切换按钮
- `chat-panel.tsx` 中的发送按钮
- `live-preview.tsx` 中的表情按钮

---

### Dialog

**用途**: 模态对话框覆盖层

**用法**:
```typescript
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

<Dialog>
  <DialogTrigger asChild>
    <Button>Open Dialog</Button>
  </DialogTrigger>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Dialog Title</DialogTitle>
      <DialogDescription>Dialog description</DialogDescription>
    </DialogHeader>
    <DialogFooter>
      <Button>Cancel</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的设置对话框

---

### Input

**用途**: 文本输入字段

**用法**:
```typescript
import { Input } from '@/components/ui/input'

<Input type="text" placeholder="Enter text..." />
<Input type="number" placeholder="Enter number..." />
<Input type="password" placeholder="Enter password..." />
<Input disabled />
```

**代码库中的示例**:
- `chat-panel.tsx` 中的消息输入
- `bottom-toolbar.tsx` 中的设置输入

---

### Label

**用途**: 具有适当可访问性的表单标签

**用法**:
```typescript
import { Label } from '@/components/ui/label'

<Label htmlFor="email">Email</Label>
<Input id="email" type="email" />
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 设置对话框中的表单标签

---

### ScrollArea

**用途**: 自定义样式的可滚动区域

**用法**:
```typescript
import { ScrollArea } from '@/components/ui/scroll-area'

<ScrollArea className="h-400">
  <div>Content with custom scrollbar</div>
</ScrollArea>
```

**代码库中的示例**:
- `chat-panel.tsx` 中的消息列表滚动区域

---

### Select

**用途**: 下拉选择输入

**用法**:
```typescript
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

<Select>
  <SelectTrigger>
    <SelectValue placeholder="Select option" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="option1">Option 1</SelectItem>
    <SelectItem value="option2">Option 2</SelectItem>
  </SelectContent>
</Select>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的 VAD 灵敏度选择器
- 设置对话框中的模型选择

---

### Separator

**用途**: 视觉分隔符/分隔线

**用法**:
```typescript
import { Separator } from '@/components/ui/separator'

<Separator />  {/* Horizontal */}
<Separator orientation="vertical" />  {/* Vertical */}
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的工具栏分隔

---

### Slider

**用途**: 范围滑块输入

**用法**:
```typescript
import { Slider } from '@/components/ui/slider'

<Slider
  value={[value]}
  onValueChange={(vals) => setValue(vals[0])}
  min={0}
  max={100}
  step={1}
/>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的音量控制
- 设置对话框中的增益控制

---

### Switch

**用途**: 切换开关

**用法**:
```typescript
import { Switch } from '@/components/ui/switch'

<Switch
  checked={enabled}
  onCheckedChange={setEnabled}
/>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的功能切换
- 设置切换开关（VAD、噪声抑制）

---

### Textarea

**用途**: 多行文本输入

**用法**:
```typescript
import { Textarea } from '@/components/ui/textarea'

<Textarea
  placeholder="Enter multi-line text..."
  value={text}
  onChange={(e) => setText(e.target.value)}
/>
```

**代码库中的示例**:
- `chat-panel.tsx` 中的消息输入区域

---

### Toast & Toaster

**用途**: 通知提示

**用法**:
```typescript
import { useToast } from '@/components/ui/use-toast'
import { Toaster } from '@/components/ui/toaster'

function Component() {
  const { toast } = useToast()

  return (
    <>
      <Button onClick={() => {
        toast({
          title: "Success",
          description: "Operation completed",
        })
      }}>
        Show Toast
      </Button>
      <Toaster />
    </>
  )
}
```

**代码库中的示例**:
- 应用程序中的错误通知
- 成功确认提示

---

### Toggle & ToggleGroup

**用途**: 切换按钮和切换组

**用法**:
```typescript
import { Toggle } from '@/components/ui/toggle'
import {
  ToggleGroup,
  ToggleGroupItem,
} from '@/components/ui/toggle-group'

<Toggle pressed={pressed} onPressedChange={setPressed}>
  Toggle
</Toggle>

<ToggleGroup type="single">
  <ToggleGroupItem value="left">Left</ToggleGroupItem>
  <ToggleGroupItem value="center">Center</ToggleGroupItem>
  <ToggleGroupItem value="right">Right</ToggleGroupItem>
</ToggleGroup>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的麦克风切换按钮

---

### Tooltip

**用途**: 悬停提示

**用法**:
```typescript
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

<TooltipProvider>
  <Tooltip>
    <TooltipTrigger>Hover me</TooltipTrigger>
    <TooltipContent>
      <p>Tooltip content</p>
    </TooltipContent>
  </Tooltip>
</TooltipProvider>
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的按钮提示
- `live-preview.tsx` 中的控制说明

---

### use-mobile Hook

**用途**: 检测移动端屏幕尺寸

**用法**:
```typescript
import { useMobile } from '@/components/ui/use-mobile'

function Component() {
  const isMobile = useMobile()
  return isMobile ? <MobileView /> : <DesktopView />
}
```

**代码库中的示例**:
- `bottom-toolbar.tsx` 中的响应式布局

---

## VTuber 组件

### ChatPanel

**位置**: `components/vtuber/chat-panel.tsx`

**用途**: 显示对话消息并处理文本输入

**功能**:
- 带时间戳的可滚动消息列表
- 用户和 AI 消息区分
- 带发送按钮的文本输入
- 连接状态显示
- 自动滚动到最新消息

**Props**: 无（使用状态存储）

**状态依赖**:
- `useConversationStore`: 消息、当前文本
- `useConnectionStore`: 连接状态

---

### LivePreview

**位置**: `components/vtuber/live-preview.tsx`

**用途**: 显示视频/Live2D 模型和状态

**功能**:
- 视频/Live2D 渲染区域
- 状态指示器徽章
- 表情控制按钮
- 连接状态显示

**Props**: 无（使用状态存储）

**状态依赖**:
- `useConversationStore`: 对话状态
- `useConnectionStore`: 连接状态

---

### BottomToolbar

**位置**: `components/vtuber/bottom-toolbar.tsx`

**用途**: 音频、设置和连接的控制面板

**功能**:
- 麦克风切换按钮
- 音量/增益滑块
- VAD 灵敏度选择器
- 设置对话框（噪声抑制、回声消除）
- 连接管理（连接/断开）
- 表情控制

**Props**: 无（使用状态存储）

**状态依赖**:
- `useAudioStore`: 录制状态、播放状态
- `useConnectionStore`: 连接状态
- `useConversationStore`: 对话状态

---

## 布局组件

### Header

**位置**: `components/layout/header.tsx`

**用途**: 带标题和品牌的应用程序页眉

**功能**:
- 应用程序标题
- 状态指示器
- 导航链接（如果有）

---

### ConnectionStatus

**位置**: `components/layout/connection-status.tsx`

**用途**: 显示当前连接状态

**功能**:
- 状态徽章（已连接、已断开、错误）
- 会话 ID 显示
- 重新连接按钮

---

## 样式规范

### Tailwind CSS

我们使用 Tailwind CSS 进行所有样式设计。主要规范：

**颜色**:
```typescript
bg-blue-500          // 主蓝色
text-gray-500        // 弱化文本
bg-gray-500/15       // 半透明背景
border-gray-200      // 边框颜色
```

**间距**:
```typescript
p-4                  // padding: 1rem
m-2                  // margin: 0.5rem
gap-4                // gap: 1rem
space-y-2            // 子元素之间的垂直间距
```

**布局**:
```typescript
flex                 // flex 容器
flex-col             // 列方向
items-center         // 项目居中对齐
justify-between      // 内容两端对齐
grid grid-cols-2     // 2 列网格
```

**响应式**:
```typescript
md:flex-row          // 中等屏幕以上使用 flex 行
lg:w-400             // 大屏幕以上宽度 400px
```

### cn() 工具函数

使用 `cn()` 工具函数进行条件 className 合并：

```typescript
import { cn } from '@/shared/utils/cn'

function Button({ variant, className }) {
  return (
    <button
      className={cn(
        'base-styles',
        variant === 'primary' && 'primary-styles',
        variant === 'secondary' && 'secondary-styles',
        className  // 允许自定义覆盖
      )}
    />
  )
}
```

### 组件变体

许多 UI 组件使用 `class-variance-authority` (cva) 模式来处理变体：

```typescript
import { cva } from 'class-variance-authority'

const buttonVariants = cva(
  'base-styles',
  {
    variants: {
      variant: {
        default: 'default-variant-styles',
        destructive: 'destructive-styles',
      },
      size: {
        sm: 'small-styles',
        default: 'default-styles',
        lg: 'large-styles',
      },
    },
  }
)
```

---

## 组件最佳实践

### 1. 组合优于配置

优先组合组件而不是使用复杂的 props：

```typescript
// 推荐
<Dialog>
  <DialogTrigger>
    <Button>打开</Button>
  </DialogTrigger>
  <DialogContent>
    {/* 内容 */}
  </DialogContent>
</Dialog>

// 避免
<Dialog trigger={<Button>打开</Button>} content={<div>...</div>} />
```

### 2. 使用状态存储

通过 Zustand 存储访问全局状态，而不是 props 传递：

```typescript
// 推荐
import { useConversationStore } from '@/shared/state/stores'

function ChatPanel() {
  const messages = useConversationStore((s) => s.messages)
  return <div>{/* 渲染消息 */}</div>
}

// 避免
function ChatPanel({ messages, onSendMessage }) {
  return <div>{/* 渲染消息 */}</div>
}
```

### 3. TypeScript 严格模式

始终为 props 和 state 添加类型：

```typescript
interface ButtonProps {
  variant?: 'default' | 'destructive' | 'outline'
  size?: 'sm' | 'default' | 'lg'
  children: React.ReactNode
  className?: string
  onClick?: () => void
}

export function Button({ variant, size, children, className, onClick }: ButtonProps) {
  // ...
}
```

### 4. 可访问性

始终包含适当的 ARIA 标签和语义化 HTML：

```typescript
<Button aria-label="切换麦克风" onClick={toggleMic}>
  <MicIcon />
</Button>

<Dialog>
  <DialogTitle>设置</DialogTitle>
  <DialogDescription>
    配置您的音频和连接设置。
  </DialogDescription>
</Dialog>
```

---

## 添加新组件

### UI 组件 (shadcn/ui)

使用 shadcn CLI：

```bash
pnpm dlx shadcn@latest add [组件名称]
```

### VTuber 组件

1. 在 `components/vtuber/` 中创建文件
2. 从 `@/components/ui` 导入 UI 组件
3. 使用状态存储来管理数据
4. 如有需要，从 index 导出

### 布局组件

1. 在 `components/layout/` 中创建文件
2. 仅保留展示逻辑
3. 使用 props 进行配置
4. 如有需要，从 index 导出


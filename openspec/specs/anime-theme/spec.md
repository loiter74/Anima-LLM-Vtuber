## Purpose
Defines the accepted behavior and requirements for the anime-theme capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: 主题色系统
系统 SHALL 定义完整的日系二次元主题色 token，包含背景色、文字色、强调色、面板色、边框色等语义化色彩变量。

#### Scenario: 主题色 token 使用
- **WHEN** 组件使用 `bg-$c-surface`、`text-$c-accent` 等 UnoCSS token
- **THEN** 渲染为对应的主题色值，全局风格统一

#### Scenario: 暗色模式
- **WHEN** 应用使用暗色模式（默认）
- **THEN** 背景为深色系，面板为半透明深色，文字为浅色，强调色为粉紫色系

### Requirement: Glassmorphism 面板
系统 SHALL 提供 glassmorphism（毛玻璃）面板样式，用于聊天面板、状态栏等容器。

#### Scenario: 半透明模糊面板
- **WHEN** 渲染 GlassPanel 组件
- **THEN** 面板具有半透明背景、`backdrop-filter: blur()`、微弱边框发光效果

### Requirement: 消息气泡样式
消息气泡 SHALL 使用圆角设计，用户消息和 AI 消息使用不同配色，带入场动画。

#### Scenario: 用户消息气泡
- **WHEN** 渲染用户消息
- **THEN** 右对齐，圆角 16px，右下角小圆角 4px，半透明蓝紫色背景

#### Scenario: AI 消息气泡
- **WHEN** 渲染 AI 回复消息
- **THEN** 左对齐，圆角 16px，左下角小圆角 4px，半透明粉色背景

### Requirement: 动画系统
系统 SHALL 提供统一的动画 keyframes，包括消息入场、脉冲、波形、淡入淡出等。

#### Scenario: 消息入场动画
- **WHEN** 新消息添加到列表
- **THEN** 消息从下方滑入 + 透明度从 0 到 1，持续 300ms

#### Scenario: 连接状态脉冲
- **WHEN** 连接状态为 connecting
- **THEN** 状态指示灯显示脉冲动画

### Requirement: 自定义标题栏样式
标题栏 SHALL 与二次元主题一致，支持拖拽区域，显示连接状态指示灯和应用名称。

#### Scenario: 标题栏渲染
- **WHEN** 应用启动
- **THEN** 标题栏使用半透明背景，左侧应用名称，右侧最小化和关闭按钮，按钮 hover 有柔和过渡

### Requirement: 连接状态指示灯
系统 SHALL 显示连接状态指示灯（绿色已连接、红色断开、黄色连接中）。

#### Scenario: 已连接
- **WHEN** Socket.IO 连接成功
- **THEN** 显示绿色圆点，带柔和发光效果

#### Scenario: 断开连接
- **WHEN** Socket.IO 断开
- **THEN** 显示红色圆点

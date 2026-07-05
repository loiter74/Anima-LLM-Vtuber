## Purpose
Defines the accepted behavior and requirements for the window-manager capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: 单窗口默认布局
系统 SHALL 默认以单窗口模式启动，窗口内左侧为 Live2D 渲染区域，右侧为聊天面板，使用响应式布局。

#### Scenario: 应用启动
- **WHEN** Electron 应用启动
- **THEN** 显示单窗口，左侧 Live2D 模型渲染区（占 50-60%），右侧聊天面板（占 40-50%），整体采用 glassmorphism 面板风格

#### Scenario: 窗口大小调整
- **WHEN** 用户拖拽窗口边缘调整大小
- **THEN** Live2D 和聊天面板按比例响应式调整，Live2D 模型自动缩放适应容器

### Requirement: Live2D 弹出分离
系统 SHALL 支持将 Live2D 区域从主窗口弹出为独立窗口，弹出后主窗口全屏显示聊天面板。

#### Scenario: 弹出 Live2D
- **WHEN** 用户点击 Live2D 区域的弹出按钮
- **THEN** Live2D 渲染在新 Electron BrowserWindow 中启动，主窗口 Live2D 区域替换为聊天面板扩展

#### Scenario: 弹出窗口关闭时回收到主窗口
- **WHEN** 弹出的 Live2D 窗口被关闭
- **THEN** Live2D 渲染回到主窗口的默认布局位置

### Requirement: 弹出窗口状态同步
弹出窗口和主窗口 SHALL 通过 IPC 实时同步 Live2D 表情、模型切换等状态。

#### Scenario: 主窗口触发表情变化同步到弹出窗口
- **WHEN** 后端发送 `expression` 事件给主窗口
- **THEN** 主窗口通过 IPC 将表情指令转发给弹出窗口，弹出窗口的 Live2D 模型执行对应表情

### Requirement: 自定义标题栏
系统 SHALL 使用无边框窗口 + 自定义标题栏，支持拖拽移动、最小化、关闭按钮，与日系二次元主题风格一致。

#### Scenario: 标题栏交互
- **WHEN** 用户拖拽自定义标题栏
- **THEN** 窗口跟随移动，标题栏显示应用名称和连接状态指示灯

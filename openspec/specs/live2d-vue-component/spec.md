## Purpose
Defines the accepted behavior and requirements for the live2d-vue-component capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Live2D 渲染组件
系统 SHALL 提供 `<Live2DRenderer>` Vue 3 组件，封装 pixi.js Application 和 pixi-live2d-display，接受 props 控制模型和表情。pixi.js SHALL 通过 ES module import（`import * as PIXI from 'pixi.js'`）加载，pixi-live2d-display SHALL 通过 `import { Live2DModel } from 'pixi-live2d-display/cubism4'` 加载。组件初始化时 SHALL 设置 `window.PIXI = PIXI` 以满足 pixi-live2d-display 内部的 Ticker 驱动依赖。

#### Scenario: 模型加载
- **WHEN** 组件挂载并通过 ES module import 加载了 pixi.js 和 pixi-live2d-display，且 PixiJS Application 创建成功
- **THEN** 加载 Live2D 模型，渲染到 canvas 元素，emit `model-loaded` 事件

#### Scenario: 模型加载失败
- **WHEN** 模型 URL 无效或网络错误
- **THEN** 组件 emit `model-error` 事件，显示占位状态

#### Scenario: window.PIXI 桥接
- **WHEN** pixi.js ES module 导入成功
- **THEN** `window.PIXI` 被设为导入的 PIXI 模块对象，使 pixi-live2d-display 可获取 `window.PIXI.Ticker` 用于模型逐帧更新

### Requirement: 表情控制
`<Live2DRenderer>` SHALL 通过 prop 接受表情指令，驱动 Live2D 模型表情切换。

#### Scenario: 切换表情
- **WHEN** `expression` prop 变化为 `"happy"`
- **THEN** Live2D 模型执行 "happy" 表情动画，按表情策略控制持续时间和强度

### Requirement: 口型同步
`<Live2DRenderer>` SHALL 支持口型同步（viseme/lip sync），根据 TTS 音频数据驱动嘴部参数。

#### Scenario: TTS 音频播放时口型同步
- **WHEN** 收到 `audio_with_expression` 事件包含音频和 viseme 数据
- **THEN** Live2D 模型嘴部参数随音频数据实时变化

### Requirement: 自动行为
`<Live2DRenderer>` SHALL 支持自动眨眼、自动注视鼠标、空闲眼球运动等自然行为。

#### Scenario: 自动眨眼
- **WHEN** Live2D 模型处于空闲状态
- **THEN** 模型以随机间隔执行眨眼动画

#### Scenario: 鼠标注视跟踪
- **WHEN** 用户在 Live2D 渲染区域内移动鼠标
- **THEN** 模型眼球跟随鼠标位置

### Requirement: 响应式缩放
`<Live2DRenderer>` SHALL 自动适应容器大小变化，保持模型在容器内居中且比例正确。

#### Scenario: 容器大小变化
- **WHEN** 窗口大小改变或弹出/回收 Live2D
- **THEN** pixi.js renderer 自适应新尺寸，模型按比例缩放，保持居中

### Requirement: 无全局脚本依赖
pixi.js 和 pixi-live2d-display SHALL NOT 通过 `index.html` 的 `<script>` 标签或 `require()` 加载。所有依赖 SHALL 通过 Vite 的 ES module 解析系统导入。

#### Scenario: 开发模式
- **WHEN** 运行 `pnpm dev` 启动 electron-vite 开发服务器
- **THEN** pixi.js 和 pixi-live2d-display 通过 Vite 的 ESM 模块解析加载，`useLive2D.ts` 中的 `import` 语句正常解析

#### Scenario: 生产构建
- **WHEN** 运行 `pnpm build` 构建生产版本
- **THEN** pixi.js 和 pixi-live2d-display 被打包进 renderer 产物，Live2D 渲染正常，不依赖 `node_modules` 目录

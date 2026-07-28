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
`<Live2DRenderer>` SHALL accept an optional versioned semantic performance plan with audio delivery and SHALL resolve it through the active model profile. The response LLM path SHALL NOT control raw Live2D parameters or motion indices.

#### Scenario: 音频开始时切换表情
- **WHEN** 当前任务的真实音频开始且携带有效的 cheerful performance plan
- **THEN** Live2D 模型在 250 ms 内淡入模型配置的柔和开心表情

#### Scenario: 无效计划
- **WHEN** performance plan 无效、过期或当前模型不支持
- **THEN** Live2D 模型保持平静待机且不执行原始动作

### Requirement: 口型同步
`<Live2DRenderer>` SHALL support lip sync from TTS audio and SHALL give the lip-sync layer exclusive ownership of `ParamMouthOpenY`. Facial expressions MAY control mouth form but SHALL NOT write mouth-open.

#### Scenario: TTS 音频播放时口型同步
- **WHEN** 收到当前任务的流式或完整 TTS 音频
- **THEN** Live2D 模型嘴部开合 SHALL follow the audio after model motion and performance overlays are applied

### Requirement: 自动行为
`<Live2DRenderer>` SHALL support automatic blinking, mouse focus, and a deterministic calm idle. For Hiyori, `Hiyori_m01` SHALL be the only automatic idle motion; unreviewed `m02`–`m10` motions SHALL NOT be selected automatically or by the LLM response path.

#### Scenario: 自动眨眼
- **WHEN** Live2D 模型处于空闲状态
- **THEN** 模型以随机间隔执行眨眼动画

#### Scenario: 平静待机
- **WHEN** 没有当前可播放语音
- **THEN** Hiyori SHALL remain on the looping `m01` calm sway

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

### Requirement: 分层表演生命周期
`<Live2DRenderer>` SHALL coordinate calm, armed, speaking, and settling states. It SHALL apply model motion and physics first, performance overlays second, and lip sync last.

#### Scenario: 正常播放完成
- **WHEN** 当前语音播放结束
- **THEN** 表情 SHALL 在 350 ms 内回到平静并继续 `m01`

#### Scenario: 播放中断
- **WHEN** 当前语音被取消、断流、任务替换或连接断开
- **THEN** 控制器 SHALL cancel pending accents, close the mouth, and return safely to calm


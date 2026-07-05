## Purpose
Defines the accepted behavior and requirements for the vue3-project-scaffold capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: electron-vite 项目初始化
系统 SHALL 使用 electron-vite 脚手架创建项目，支持 main/renderer/preload 三进程分离，TypeScript 严格模式，Vite 开发服务器 HMR。

#### Scenario: 开发模式启动
- **WHEN** 运行 `pnpm dev`
- **THEN** electron-vite 启动 Vite 开发服务器 + Electron，支持 HMR 热更新

#### Scenario: 生产构建
- **WHEN** 运行 `pnpm build`
- **THEN** electron-vite 构建 main/renderer/preload 三部分产物，输出到 `dist/`

### Requirement: UnoCSS 集成
系统 SHALL 集成 UnoCSS 作为样式引擎，使用 `@unocss/preset-uno`（兼容 Tailwind 语法），支持自定义主题 token。

#### Scenario: 原子化 class 使用
- **WHEN** 在 Vue 模板中使用 `class="bg-$c-surface text-$c-accent rounded-xl p-4"`
- **THEN** UnoCSS 自动生成对应 CSS 规则

#### Scenario: 自定义主题 token
- **WHEN** 在 `uno.config.ts` 中定义 theme tokens
- **THEN** 组件可通过 `$c-*` 变量引用颜色，通过 `$spacing-*` 引用间距

### Requirement: TypeScript 严格模式
系统 SHALL 启用 TypeScript strict mode，所有 `.ts`/`.vue` 文件通过类型检查。

#### Scenario: 类型检查通过
- **WHEN** 运行 `pnpm typecheck` (vue-tsc --noEmit)
- **THEN** 无类型错误，所有组件 props、emit、store 均有类型推断

### Requirement: 项目目录结构
项目 SHALL 按照功能模块组织：`components/`（按 chat/live2d/layout/shared 分组）、`composables/`、`stores/`、`types/`、`styles/`。

#### Scenario: 面试官浏览项目
- **WHEN** 面试官打开 `frontend/src/` 目录
- **THEN** 能通过目录名快速定位到聊天组件、Live2D 组件、状态管理、类型定义

### Requirement: 启动脚本适配
`scripts/start.py` SHALL 适配新的前端启动方式，支持 `--mode desktop` 调用 `pnpm dev` 启动 Vue 前端。

#### Scenario: 通过启动脚本启动
- **WHEN** 运行 `python scripts/start.py --mode desktop`
- **THEN** 后端启动 + 前端 `pnpm dev` 自动启动

# ANIMETTA PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-15
**Commit:** 10735c3
**Branch:** main

> Primary knowledge base: [CLAUDE.md](CLAUDE.md). This AGENTS.md is the quick-reference map.
> Sub-AGENTS.md: [src/animetta/](src/animetta/AGENTS.md) · [src/animetta/core/](src/animetta/core/AGENTS.md) · [orchestration/](src/animetta/orchestration/AGENTS.md) · [orchestration/graph/](src/animetta/orchestration/graph/AGENTS.md) · [services/](src/animetta/services/AGENTS.md) · [memory/](src/animetta/memory/AGENTS.md) · [config/](src/animetta/config/AGENTS.md) · [tools/](src/animetta/tools/AGENTS.md) · [tools/minecraft/](src/animetta/tools/minecraft/AGENTS.md) · [avatar/](src/animetta/avatar/AGENTS.md) · [inspection/](src/animetta/inspection/AGENTS.md) · [frontend/](frontend/AGENTS.md) · [design-system/](design-system/AGENTS.md) · [evaluations/](evaluations/AGENTS.md) · [tests/](tests/AGENTS.md) · [docs/adrs/](docs/adrs/AGENTS.md)

## OVERVIEW

AI virtual companion / VTuber framework. Python backend (**Starlette + LangGraph + Socket.IO ASGI**, not FastAPI despite legacy docs) + Vue 3 Electron frontend + Live2D avatar.

## STRUCTURE

```
./
├── src/animetta/              # Python backend (~409 files, 37K+ lines Python + 11K TS/Vue)
│   ├── core/               # Entry + service container (socketio_server, service_pool, model_loading_manager, redis_checkpoint)
│   ├── orchestration/      # LangGraph state graph + WebSocket server
│   ├── services/           # LLM / ASR / TTS / VAD / Singing / Meme / Live2D / Bilibili
│   ├── memory/             # V2 atom-based memory (Chroma + SQLite FTS5)
│   ├── config/             # Pydantic configs + @ProviderRegistry
│   ├── avatar/             # Live2D emotion/expression analysis
│   ├── tools/              # Tool calling + MCP bridge + Minecraft bot (⚠️ Node.js hybrid)
│   ├── tracing/            # OpenTelemetry observability
│   ├── notifier/           # Alert channels (Discord, Feishu, Email)
│   ├── inspection/         # Health/telemetry background checks
│   └── utils/              # Helpers
├── frontend/               # Vue 3 + TypeScript + Vite (UnoCSS, Pinia, pixi.js, Electron)
├── config/                 # YAML config files (personas, services, tools, singing)
├── tests/                  # pytest suite (120 files, asyncio_mode=auto)
├── docs/                   # ADRs (11), plans, benchmarks, external references
├── scripts/                # anima_cli (RVC training), bench (39KB), validate-events
├── design-system/          # Visual design spec (HTML spec sheets from uno.config.ts)
├── evaluations/            # Standalone RAG evaluation framework (Python)
├── observability/          # Docker-compose for Grafana/Prometheus/Tempo/Loki/OTel stack
├── data/ + memory_db/      # ⚠️ Dual runtime data dirs (Chroma, SQLite, Wiki, logs)
└── .claude/                # Claude skills
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add LLM provider | `src/animetta/services/llm/` | Create class, register via `@ProviderRegistry` |
| Add ASR/TTS provider | `src/animetta/services/{asr,tts}/` | Same pattern as LLM |
| Add graph node | `src/animetta/orchestration/graph/` | Follow node pattern in `__init__.py` |
| Add tool | `src/animetta/tools/base.py` or `custom_tools.py` | Use `@tool` decorator |
| Add persona | `config/personas/` + `src/animetta/config/persona/` | YAML + Pydantic |
| Fix WebSocket route | `src/animetta/orchestration/server/routes.py` | **386 lines - known hotspot** |
| Change memory behavior | `src/animetta/memory/v2/` | Atom-based V2 architecture, see ADR-005 |
| Fix Live2D expression | `src/animetta/avatar/` + `frontend/src/components/live2d/` | |
| Add singing feature | `src/animetta/services/singing/` | RVC/SVC pipeline + mixer |
| Minecraft bot | `src/animetta/tools/minecraft/` | ⚠️ Node.js bot inside Python tree |
| Run tests | `PYTHONPATH=src python -m pytest tests/ -v` | asyncio_mode=auto |
| Type check | `mypy src/ --ignore-missing-imports` | |

## CONVENTIONS

- **Python 3.13+** — `X | None` not `Optional[X]`
- **Pydantic V2** — `model_config = ConfigDict(...)` not `class Config:`
- **Async-first** — all I/O is async
- **Type hints required** on all public functions
- **Logging**: `loguru` logger, English only
- **Provider plugin pattern**: `interface.py` ABC → implementations → factory → `__init__.py` re-exports
- **TDD preferred** — write tests first
- **Frontend styling** — follow `STYLE_GUIDE.md`; use design-system tokens and UnoCSS utilities, not raw hardcoded colors.

## VIBE CODING 八荣八耻

与 AI 协作（Codex / Claude / Copilot）时的铁律：

| # | 以…为耻 | 以…为荣 |
|---|---------|---------|
| 1 | 臆猜接口 | 查档求证 |
| 2 | 模糊开工 | 对齐需求 |
| 3 | 脑补业务 | 请示规则 |
| 4 | 新增冗余 | 复用存量 |
| 5 | 省略校验 | 完备测例 |
| 6 | 乱改架构 | 恪守规范 |
| 7 | 不懂装懂 | 坦诚存疑 |
| 8 | 批量乱改 | 分步迭代 |

**核心原则**：别让 AI 瞎猜，喂它准确信息。AI 能力强但没有项目上下文，你不给它准确信息它就只能臆猜——以上每一条都在堵这个漏洞。

## AGENT WORKFLOW RULES

### Testing (QA)
- **启动测试步骤时，必须使用 `qa` skill** — 配合 `playwright` 技能进行页面捕获
- **每次测试前必须重新获取数据** — 禁止使用上一次 playwright 的缓存结果，必须重新捕获页面
- **QA 测试流程**：`qa` skill → Playwright 页面捕获（全新获取）→ 发现/修复问题

### 服务启动（Docker 启动协议）

> **核心原则**：成功判定 = 容器健康检查通过 + API 返回 200，**不依赖进程退出**。
> 禁止在主 agent 启动服务 — 会卡住无法校验。所有启动操作必须通过 `task()` 子 agent 执行。

| 步骤 | 操作 | 判定标准 |
|------|------|----------|
| **1. 清理容器** | `docker compose down` 停止并移除旧容器 | 容器已清理 |
| **2. 构建镜像** | `docker compose build` 或 `docker compose -f docker-compose.cpu.yml build`（CPU 模式） | 构建成功无报错 |
| **3. 启动服务** | `docker compose up -d` 或 `docker compose -f docker-compose.cpu.yml up -d`（CPU 模式） | 容器启动成功 |
| **4. 轮询健康** | `curl -s http://localhost/health` 每 5 秒一次，最多 24 次（120 秒） | HTTP 200 + 响应体含 `"status":"ok"` |
| **5. 验证前端** | `curl -s http://localhost` 每 5 秒一次，最多 12 次（60 秒） | HTTP 200 |
| **6. 报告成功** | 子 agent 输出 `[OK] Docker container healthy, frontend accessible on port 80` | 服务完全就绪 |

**关键约束**：
- 每步失败即停，不得跳过轮询直接假设成功
- 启动后 **必须用 curl 轮询健康检查**，不能只检查容器状态（服务可能还没就绪）
- 前端通过 nginx 反向代理在 80 端口提供服务
- 日志中不允许出现任何 Traceback 或 ERROR 级别日志（使用 `docker compose logs` 检查）
- 代码变更后 **必须完整走一遍 Docker 启动协议**，确保服务可用

**Docker 模式选择**：
- **GPU 模式**（默认）：`docker compose up -d --build` — 需要 NVIDIA GPU + nvidia-container-toolkit
- **CPU 模式**：`docker compose -f docker-compose.cpu.yml up -d --build` — 无 GPU 环境

**常用 Docker 命令**：
```bash
# 查看日志
docker compose logs -f animetta

# 进入容器
docker compose exec animetta bash

# 重启服务
docker compose restart animetta

# 停止服务
docker compose down
```

## ANTI-PATTERNS (THIS PROJECT)

- ❌ Never import from removed modules: `pipeline/`, `events/`, `handlers/`, `adapters/`, old `core/`, `services/conversation/`, old `state/`
- ❌ Never rewrite business logic in graph nodes — reuse `services/` implementations
- ❌ Never call `ctx.close()` on ServicePool — destroys shared LLM/TTS/ASR engines
- ❌ Never use real-time `getBounds()` in Live2D scaling — use cached `baseBounds`
- ❌ Never add EventBus back — LangGraph is the only orchestration mode (ADR-001)
- ❌ Pydantic V2 only — `class Config:` is forbidden
- ❌ Never start backend in main agent — spawn sub-agent via `task()`, or agent will hang
- ❌ Never reuse previous Playwright/QA results — always re-capture fresh test data
- ❌ Never skip the Docker startup protocol after code changes — curl-polling is mandatory, not optional
- ❌ Never assume process exit = service ready — port listening + HTTP 200 is the only valid success signal

## DEPRECATED

| Item | Location | Notes |
|------|----------|-------|
| `scripts/start.py` | **REMOVED** — references are stale | Use `python -m animetta.core.socketio_server` directly |
| `--mode` / `--no-app` flags | (were in scripts/start.py) | No effect; file is gone |

## COMMANDS

```bash
# Docker (recommended)
docker compose up -d --build              # GPU mode
docker compose -f docker-compose.cpu.yml up -d --build  # CPU mode
docker compose down                       # Stop
docker compose logs -f animetta           # Logs

# Backend only (local)
PYTHONPATH=src python -m animetta.core.socketio_server

# Tests
PYTHONPATH=src python -m pytest tests/ -v
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta --cov-report=term-missing

# Type + lint
mypy src/ --ignore-missing-imports
ruff check src/ tests/
```

Two DeepSeek models are available via `oh-my-openagent.json`:

| Model | Agent/Category | Role |
|-------|---------------|------|
| **flash** (`deepseek/deepseek-v4-flash`) | sisyphus, sisyphus-junior, explore, librarian, visual-engineering, quick, unspecified-low, unspecified-high, writing | 快速、低成本，适合确定性强的任务 |
| **pro** (`deepseek/deepseek-v4-pro`) | oracle, prometheus, metis, momus, ultrabrain, deep, artistry | 高推理能力，适合复杂/不确定/高代价场景 |

### Decision Matrix

When delegating an implementation task (always use `deep` or `unspecified-high`), choose:

| 场景 | Use | 模型 |
|------|-----|------|
| 改一个文件、模式已知、改什么怎么写很清楚 | `unspecified-high` | flash |
| 跨 2+ 模块、需要理解代码结构 | `deep` | **pro** |
| 新功能设计、需要做 trade-off 选型 | `deep` | **pro** |
| 批量执行、但每步逻辑简单（如替换字符串、加字段） | `unspecified-high` | flash |
| 调试复杂 bug、需要追踪调用链 | `deep` or `oracle` | **pro** |
| 纯搜索/查找（不修改代码） | `explore` / `librarian` | flash |
| 纯 UI 视觉任务 | `visual-engineering` | flash |
| 单文件 typo/简单修改 | `quick` | flash |
| 硬核逻辑、算法、数学 | `ultrabrain` | **pro** |
| 非常规思路、需要跳出框架 | `artistry` | **pro** |

**Rule of thumb:** 如果不确定是 `deep` 还是 `unspecified-high`，选 `deep`（pro）。宁可贵一点，不要因为模型不够强而反复重做。

### Pro Trigger Examples

以下情况**必须**用 pro 类别（`deep` / `ultrabrain` / `oracle`）：

- **首次接触的代码模块**——不熟悉内部结构，需要 pro 理解上下文
- **跨 2 个以上模块的改动**——需要全局推理保证一致性
- **设计/选型决策**——架构方案、API 设计、数据流设计
- **复杂调试**——2 次尝试没解决的 bug
- **高代价区域**——核心逻辑、对外接口、生产关键路径
- **模棱两可的需求**——用户没说清楚，需要推理多种可能性

以下情况**可以**用 flash 类别（`unspecified-high` / `quick` / `explore`）：

- **搜索/查找**——找文件、找模式、找定义
- **已知模式的重复操作**——加个字段、改个类型、复制已有模式
- **纯执行**——实现方案已经定好了，只差写代码
- **低风险修改**——工具脚本、测试辅助、注释文档

## NOTES

- `orchestration/server/routes.py` at 386 lines is a known hotspot — thin dispatch preferred
- Backend coverage at ~70%, targeting 70%. Frontend has 20 vitest test files (happy-dom env, `src/**/*.test.ts`).
- 11 ADRs in `docs/adrs/`: LangGraph, Hybrid Search, Plugin Architecture, Streaming, Wiki Memory, +6 more (see [docs/adrs/AGENTS.md](docs/adrs/AGENTS.md))
- Two runtime data directories: `data/` (chroma_db, stats) + `memory_db/` (wiki, chroma, sqlite, raw) — designed split
- TTS has 9 providers with core/contrib layering (see services/AGENTS.md)
- `tools/minecraft/bot/` is a Node.js package embedded in the Python tree — cross-language hybrid (see [tools/minecraft/AGENTS.md](src/animetta/tools/minecraft/AGENTS.md))
- Frontend runs as Vite dev server (port 3000); Electron builder not yet configured
- Notifier has 3 channels: Discord, Feishu, Email
- Inspection scheduler runs background health checks every N hours, results in StatsStore


# Animetta Design System — Agent guide

> This file is read by coding agents (Claude Code, Cursor, Codex, Copilot Chat).
> If you are an agent: **read the files referenced below before answering any
> question about Animetta's UI, colors, type, components, or layout.**

## What this is

A canonical reference for Animetta's visual system. The HTML files here are
not a Storybook or a runtime — they are **spec sheets**. Each one documents a
slice of the system and lists the exact tokens, sizes, paddings, and component
APIs that the live Vue codebase uses.

The tokens themselves are mirrored 1:1 from `frontend/uno.config.ts`, so
nothing in this folder ever contradicts the source of truth — but the spec
explains the *intent* behind each token, which `uno.config.ts` does not.

## File map — read in this order for any UI task

| File | Read when you need to… |
|---|---|
| `brand.html` | Set tone of voice, lay out a logo/lockup, write copy for chat vs. system surfaces |
| `colors.html` | Pick a color. **Do not invent new hex codes** — every role has an assigned token |
| `typography.html` | Choose a font size. Animetta has 9 sizes total; do not introduce new ones |
| `spacing.html` | Pick padding, radius, shadow, easing, transition duration |
| `iconography.html` | Add a section icon or background scene; follow the size ladder and composition rules |
| `components.html` | Build any UI element. Every card lists tokens + Vue/UnoCSS class names |
| `ui-kit.html` | Confirm how a new piece fits into the full app shell (titlebar / drawer / Live2D stage / chat) |
| `colors_and_type.css` | The token source. Import this if you're building an HTML preview outside the Vue app |
| `USAGE.md` | How tokens map to UnoCSS classes already wired in the Animetta repo |

## Hard rules — never break these without asking the user

1. **Never invent a color outside `colors.html`'s role table.** If you need a new color, escalate; do not add a `bg-purple-500` or similar Tailwind preset.
2. **Type stack is OS-only.** Do not add a `<link>` to a webfont — the project deliberately uses native CJK fonts.
3. **Two voices, never mixed.** Character voice in `<MessageBubble>` content; system voice in pills/badges/toasts. See `brand.html § Voice & tone`.
4. **Glass panels stack: bg → surface → panel → card.** Don't introduce a fifth lighter shade — use a border or glow instead.
5. **Round corners default to `rounded-xl` (12 px).** No 90-degree corners anywhere except the window itself.
6. **Motion budget: 150 / 200 / 300 ms × `ease-out-expo` or `ease-back-soft`.** Anything else needs justification.

## Where the corresponding code lives

| Spec file | Code path in your Animetta repo |
|---|---|
| `brand.html` | `frontend/public/favicon.svg`, `src/views/Welcome*.vue` |
| `colors.html`, `typography.html`, `spacing.html` | `frontend/uno.config.ts` |
| `iconography.html` | `frontend/public/icons/`, `frontend/public/backgrounds/`, `src/components/settings/BackgroundSettings.vue` |
| `components.html § Glass panel` | `src/components/shared/GlassPanel.vue` |
| `components.html § Buttons` | `src/components/shared/AnimatedButton.vue` |
| `components.html § Chat bubbles` | `src/components/chat/MessageBubble.vue` |
| `components.html § Activity indicators` | `src/components/chat/TypingIndicator.vue`, `SpeakingIndicator.vue` |
| `components.html § Input bar` | `src/components/chat/InputBar.vue` |
| `components.html § Title bar` | `src/components/layout/TitleBar.vue` |
| `components.html § Subtitle overlay` | `src/components/live2d/SubtitleOverlay.vue` |
| `ui-kit.html` | `src/components/layout/AppLayout.vue` + `InteractivePanel.vue` |

## Typical workflow

When the user says "add a `<NewSomething>` component":

1. Open `components.html` and find the closest existing card. Reuse its tokens.
2. Open the matching Vue component in `frontend/src/components/` and copy its
   structural pattern (`<script setup lang="ts">`, Composition API, Pinia
   store, UnoCSS shortcut on the root).
3. If the new component is novel enough to deserve its own card, append it to
   `components.html` so the next agent finds it.
4. If the new component uses any new token, add it to BOTH
   `colors_and_type.css` AND `frontend/uno.config.ts → theme.colors`. Document
   the role in the appropriate spec file.
5. 启动测试步骤时，要使用qa skill，并使用playwright技能进行页面捕获，在测试前不可以使用上一次playwright的结果，必须重新获取测试数据
6. 启动服务需要单开子agent 使用 Docker 启动协议（docker compose up -d --build），保证无任何报错信息出现在日志中
7. 要及时定期检查子agent是否卡住，如果卡住要自行解决。


## What NOT to do

- Don't open multiple spec files "just to look around" — pick the one that
  matches the user's task (table above) and read only that one.
- Don't paraphrase the spec back at the user. They have the spec; they want
  the code change.
- Don't re-derive the design philosophy from the screenshots. The pillars
  and voice are written in `brand.html` — quote them if needed.
- 不要启动用主agent启动后端服务，这会导致主agent卡住没有相应，无法正常校验程序

## 架构图/图示规范

生成架构图、流程图、决策图时，遵循以下规范：

### 存储位置

- **位置**: `C:\Users\30262\Documents\my-llm-wiki\my-llm-wiki\Excalidraw\`
- **格式**: `.canvas` (Obsidian JSON Canvas)
- **工具**: 使用 `json-canvas` skill 生成

### 目录结构

```
Excalidraw/
└── {项目名}/                    ← 大项目
    ├── 01-项目架构总览.canvas   ← 整体架构
    ├── 02-核心模块.canvas       ← 模块概览
    └── {子决策}/                ← 子项目/子决策
        ├── 01-xxx.canvas
        ├── 02-xxx.canvas
        └── ...
```

### 分层原则

| 层级 | 内容 | 示例 |
|------|------|------|
| **顶层** | 整个项目的核心架构、模块关系 | Animetta 整体架构 |
| **子目录** | 某个子模块/子决策的详细设计 | MC-Bot Voyager 升级 |

**关键**: 子决策必须放在子目录下，不要和大项目架构混在一起。

### 设计规范

1. **间距**: 节点之间至少 50px，分组内至少 20px padding
2. **分组**: 用 `group` 节点组织相关内容，带颜色标签
3. **节点大小**: 文本节点 200-300px 宽，避免过窄导致文字换行过多
4. **颜色**: 使用预设颜色 (1-6)，含义一致：
   - `1` = 红 = 必做/关键
   - `3` = 黄 = 警告/依赖
   - `4` = 绿 = 完成/新增
   - `5` = 青 = 标题/信息
   - `6` = 紫 = 可选/高级
5. **边**: 带标签说明关系，颜色与相关节点一致
6. **图和说明不分开**: 图就是图，不要在图下面加说明段落。如果非要放文字说明，放在图的旁边（作为图的一部分），不要单独成段

### 禁止事项

- ❌ 不要把子决策图放在大项目根目录
- ❌ 不要把所有内容挤在一张图里（拆分成多张）
- ❌ 不要用太小的节点（<150px 宽）
- ❌ 不要省略分组标签（让人一眼看出结构）
- ❌ 不要在图下面放说明文字（说明放在图上旁边）

---

## DEBUGGING LESSONS LEARNED

### 2026-06-20: MBTI 数值不显示

**问题**: 前端 PersonalityPanel 没有显示 MBTI 数值（ei, sn, tf, jp）。

**尝试了 3 次修复都失败**:
1. 后端在 `persona:updated` 事件中发送 MBTI 数据 → 只在切换人格时触发，初始加载不触发
2. 后端在 `persona:list` 事件中也返回 MBTI 数据 → 代码正确，但 `PersonaHandlers.global_config` 是 `None`
3. 修改 `PersonaHandlers` 接受 `base` 参数 → `base.global_config` 也是 `None`

**Root Cause**: `create_server(config)` 把 config 存到了 `self.config`，但没有调用 `set_config(config)` 把它传递给路由处理器。

**数据流**:
```
socketio_server.py → create_server(config) → WebSocketServer(config)
                                              │
                                              ├─ setup_routes() → RouteHandlers → PersonaHandlers(base)
                                              │
                                              └─ ❌ 没有调用 set_config(config)
                                                  └─ route_handlers.global_config = None
```

**最终修复**: 在 `create_server` 中添加 `server.set_config(config)` 调用。

**教训**:
1. **不要猜测** — 前 3 次修复都是在猜测问题所在，没有追踪完整的数据流
2. **添加诊断工具** — 第 4 次才添加 logging，立即发现了 `global_config=None`
3. **追踪整条链路** — 问题不在 PersonaHandlers，而在更上游的 `create_server`

### 调试流程检查清单

当修复无效时:
- [ ] 是否添加了诊断 logging?
- [ ] 是否追踪了完整的数据流?
- [ ] 是否在正确的层修复问题?
- [ ] 是否检查了初始化顺序?

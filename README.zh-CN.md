<p align="center">
  <h1 align="center">🤖 Animetta — AI 虚拟伴侣 / VTuber 框架</h1>
  <p align="center">
    可配置、可扩展的 AI 虚拟伴侣框架<br>
    插件化架构 · LangGraph 编排 · 混合记忆 · Live2D 驱动 · 多模态交互
  </p>
  <p align="center">
    <strong>简体中文</strong> &nbsp;|&nbsp; <a href="README.md">English</a>
  </p>
</p>

<img width="1673" height="941" alt="Animetta Live2D 虚拟角色说话口型" src=".github/assets/readme-cover.webp" />

> 详细文档以英文为主，本页为快速入门与概览。完整内容请参考 [docs/](docs/) 与 [English README](README.md)。

---

## ✨ 项目亮点

- **LangGraph 状态图编排** — 有向图 + 条件路由 + 工具调用循环 + 中断恢复
- **插件化 Provider 架构** — `@ProviderRegistry` 装饰器注册新服务商，零侵入核心代码
- **混合记忆系统** — Chroma 向量搜索 (70%) + SQLite FTS5 (30%) + Markdown Wiki
- **Live2D 情感驱动** — LLM 输出 → 情感分析 → Live2D 参数实时映射
- **全链路可观测** — OpenTelemetry 追踪 + Prometheus 指标 + Stats Dashboard

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     前端 (Vue 3 + Vite)                          │
│              Live2D 渲染 · 聊天 UI · 统计面板                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Socket.IO / REST
┌──────────────────────────▼──────────────────────────────────────┐
│                WebSocket Server (Starlette + Socket.IO ASGI)     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  LangGraph 编排引擎                               │
│   ASR → Persona → LLM(+RAG) → Emotion(→Live2D) → Tool/Output    │
└─────────────────────────────────────────────────────────────────┘
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   Services            Memory             Tracing
  LLM/ASR/TTS       Chroma+SQLite       OTel+Stats
```

> 完整架构说明见 [docs/architecture/overview.md](docs/architecture/overview.md)。

### 架构地图

代码库可分解为四个区域、15 个分层（括号内为架构知识图谱统计的节点数）：

| 区域 | 分层 | 关键路径 |
|------|------|----------|
| **后端运行时** | LangGraph 编排 (63) · Provider 服务 (129) · 产品工具与 Minecraft (142) · 人格与 EffectiveConfig (64) · 记忆与 Live2D (32) · 后端平台核心 (70) · 宿主机服务包 (10) | `src/animetta/` · `src/animetta_qwen_tts/` · `src/animetta_rvc_host/` |
| **前端** | 前端应用 (138) · 前端资源 (56) · Electron 壳与构建 (54) | `frontend/src/` · `frontend/public/` |
| **配置与基础设施** | 运行时配置 (30) · 基础设施与 CI/CD (22) | `config/` · `docker/` · `observability/` · `.github/workflows/` |
| **开发者面** | 开发工具与脚本 (78) · 评测与契约 (28) · Skill 与文档 (17) | `tooling/` · `scripts/` · `evaluations/` · `.agents/skills/` |

---

## 🗺️ 代码导览

一条贯穿真实代码的十步阅读路径：

1. **项目总览** — 本页 + [架构概览](docs/architecture/overview.md)。
2. **前端入口** — [`frontend/src/main.ts`](frontend/src/main.ts) 挂载 Vue 3 应用，[`App.vue`](frontend/src/App.vue) 组织 Live2D 渲染、聊天 UI 与面板。
3. **LangGraph 编排引擎** — [`orchestrator.py`](src/animetta/orchestration/graph/orchestrator.py) 构建有向状态图；[`state.py`](src/animetta/orchestration/graph/state.py) 定义贯穿 ASR → Persona → LLM → Emotion 的 `AgentState`。
4. **提示词与人格** — [`prompting/sources.py`](src/animetta/orchestration/prompting/sources.py) 组装人格与护栏感知的系统提示词。
5. **实时服务器** — [`websocket.py`](src/animetta/orchestration/server/websocket.py) 管理会话与事件流，[`routes.py`](src/animetta/orchestration/server/routes.py) 声明 Socket.IO/REST 路由。
6. **可替换 Provider** — [`services/llm/`](src/animetta/services/llm/) · [`services/tts/`](src/animetta/services/tts/) · [`services/asr/`](src/animetta/services/asr/) 按 interface → implementation → factory → export 暴露插件工厂。
7. **混合记忆** — [`memory/v2/context.py`](src/animetta/memory/v2/context.py) 融合 Chroma 向量、SQLite FTS5 与 Markdown Wiki（ADR-005）。
8. **Minecraft 产品工具** — Python 仓库中的 Node.js 适配器 [`tools/minecraft/`](src/animetta/tools/minecraft/)，向编排器暴露世界操作工具。
9. **Live2D 情感映射** — [`avatar/performance.py`](src/animetta/avatar/performance.py) 将情感输出实时映射为 Live2D 参数。
10. **配置与工具注册** — [`pyproject.toml`](pyproject.toml) 锁定 Python 3.13 后端，[`config/tools.yaml`](config/tools.yaml) 注册产品工具。

---

## 🚀 快速开始

### 前置要求

- **Python 3.13**（工具链 ruff/mypy 目标版本）
- **Node.js 20+** 与 **pnpm**
- _（可选）_ NVIDIA GPU + nvidia-container-toolkit（GPU 模式）

### 1. 安装依赖

```bash
pip install -r requirements.txt
cd frontend && pnpm install
```

### 2. 配置

编辑 `config/animetta.yaml` 选择人格，并为 `test`、`smoke`、`production` 三个 profile 声明完整服务映射。服务选择只能写在这份清单中；环境变量只传 profile、endpoint 和 secret。

```bash
cp .env.example .env
# 选择 profile，并填写它实际需要的 key：
#   ANIMETTA_PROFILE="test"
#   DEEPSEEK_API_KEY="..."
#   DASHSCOPE_API_KEY="..."
#   MIMO_API_KEY="..."
#   QWEN_TTS_API_KEY="..."
```

### 3. 启动

```bash
# 后端
python -m animetta.core.socketio_server

# 前端（另开终端）
cd frontend && pnpm dev
```

### 构建并启动个人版本（推荐）

```bash
# 自动启动/复用宿主机 Qwen，并构建、启动 Animetta
py -3.13 scripts/runtime_lifecycle.py anima-up
```

这是唯一面向日常个人使用的构建入口。CI 和内部验收仅通过 `ANIMETTA_PROFILE` 切换 `smoke` 或 `selftest`，仍复用同一份 Compose 文件。

启动后前端由 nginx 提供在 **80 端口**，后端健康检查为 `http://localhost/health`。停止应用使用 `py -3.13 scripts/runtime_lifecycle.py anima-down`；该命令会保留已加载的 Qwen 进程，方便下次快速启动。

> 详细部署：[Docker 部署](docs/deployment/docker.md) · [Zeabur 部署](docs/deployment/zeabur.md)

---

## 🔧 核心模块

| 模块 | 说明 | 文档 |
|------|------|------|
| **LangGraph 引擎** | 有向图编排 + 条件路由 + 工具循环 | [架构概览](docs/architecture/overview.md) |
| **Provider 插件** | `@ProviderRegistry` 注册 LLM/ASR/TTS/VAD | [工具参考](docs/reference/tools.md) |
| **混合记忆** | Chroma + SQLite FTS5 + Wiki + 梗学习 | ADR-002, ADR-005 |
| **Live2D 情感** | LLM → 情感标签 → Live2D 参数（6 种基础情感） | ADR-009 |
| **Minecraft bot** | Mineflayer + 解耦的外部 Voyager 运行时 | [MC 架构](docs/development/minecraft-bot-architecture.md) |
| **可观测性** | OTel + Prometheus + Stats Dashboard | ADR-006 |

---

## 📚 文档导航

| 主题 | 位置 |
|------|------|
| 架构总览 | [docs/architecture/](docs/architecture/) |
| 架构决策记录 (11 个 ADR) | [docs/adrs/](docs/adrs/) |
| 后端 / Socket.IO API 参考 | [docs/reference/](docs/reference/) |
| 测试指南 | [docs/development/testing.md](docs/development/testing.md) |
| 部署（Docker / Zeabur） | [docs/deployment/](docs/deployment/) |
| 设计系统 | [design-system/](design-system/) |
| Agent 协作规范 | [AGENTS.md](AGENTS.md) |

---

## 📄 License

[MIT License](LICENSE) — Copyright (c) 2026 Cowork

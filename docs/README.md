# Animetta 项目文档

AI 虚拟伴侣/VTuber 框架。

---

## 文档导航

### 开发指南

| 文档 | 描述 |
|------|------|
| [快速开始](development/quickstart.md) | 5 分钟运行项目 |
| [添加服务](development/adding-services.md) | 扩展 LLM/ASR/TTS 服务 |

### 架构设计

| 文档 | 描述 |
|------|------|
| [架构总览](architecture/overview.md) | C4 图、LangGraph 流程、核心组件 |
| [设计模式](architecture/patterns.md) | 6 种设计模式应用 |
| [ADR 决策记录](adrs/) | 架构决策记录 |

### 功能模块

| 文档 | 描述 |
|------|------|
| [Socket.IO API](reference/socket-api.md) | 前后端事件接口 |
| [后端 API](reference/backend-api.md) | HTTP REST + Socket.IO 接口层次 |
| [Docker 部署](deployment/docker.md) | Docker Compose 部署指南 |
| [Zeabur 部署](deployment/zeabur.md) | Zeabur 平台部署指南 |
| [测试指南](development/testing.md) | pytest 约定与覆盖率目标 |
| [AI UI 工作流](development/ai-ui-workflow.md) | 基于设计系统进行 UI 优化 |
| [RVC 训练指南](development/rvc-training-guide.md) | 角色唱歌模型训练流程 |
| [健康门禁记录](development/health-advisories.md) | 当前健康检查 advisory |
| [工具系统](reference/tools.md) | Tools / MCP / Minecraft 工具说明 |
| [Minecraft Bot 架构说明](development/minecraft-bot-architecture.md) | Python bridge、Node Mineflayer、Voyager 技能与生存循环 |
| [RAG 评估报告](reference/rag-evaluation-report.md) | RAG 质量评估结果 |

### 外部参考

| 文档 | 描述 |
|------|------|
| [AIRI Stage UI Kit](external/AIRI%20Stage%20UI%20Kit.html) | 外部 UI 规格参考 |
| [前端截图](external/frontend-screenshot.png) | 历史前端截图 |

### 实现计划

| 文档 | 描述 |
|------|------|
| [历史计划](plans/) | 已完成和计划中的功能 |

---

## 项目结构

```
src/animetta/
├── core/                 # 入口点 + 服务容器
├── orchestration/       # LangGraph 状态图 + WebSocket 服务器
│   ├── graph/           # 7 个节点 + builder + orchestrator
│   └── server/          # Socket.IO 路由 + 会话管理
├── services/             # LLM / ASR / TTS / VAD 实现
├── memory/               # Wiki 记忆架构 (Chroma + SQLite)
├── config/               # Pydantic 配置 + 服务注册
├── avatar/               # Live2D 表情/情绪分析
├── tools/                # 工具调用 + MCP 桥接
├── tracing/              # OpenTelemetry 可观测性
└── utils/                # 工具函数
```

---

## 快速开始

```bash
# 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 API Key

# Docker 启动 (推荐)
docker compose up -d --build

# 检查健康状态
curl -s http://localhost/health

# 查看日志
docker compose logs -f animetta

# 停止服务
docker compose down
```

---

## 技术栈

- **后端**: Python, FastAPI, Socket.IO
- **前端**: Electron, Vue 3 + TypeScript + Vite
- **LLM**: GLM, OpenAI, Ollama
- **ASR**: FasterWhisper, GLM
- **TTS**: Edge TTS, GLM
- **VAD**: Silero

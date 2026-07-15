<p align="center">
  <h1 align="center">🤖 Animetta — AI Virtual Companion / VTuber Framework</h1>
  <p align="center">
    A configurable, extensible AI companion framework.<br>
    Plugin architecture · LangGraph orchestration · Hybrid memory · Live2D-driven · Multimodal interaction
  </p>
  <p align="center">
    <a href="README.zh-CN.md">简体中文</a> &nbsp;|&nbsp; <strong>English</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Vue_3-vite-green?logo=vue.js" alt="Vue 3">
    <img src="https://img.shields.io/badge/LangGraph-orchestration-orange" alt="LangGraph">
    <img src="https://img.shields.io/badge/Starlette-Socket.IO_ASGI-purple" alt="Starlette">
    <img src="https://img.shields.io/badge/OpenTelemetry-tracing-teal" alt="OpenTelemetry">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</p>

<img width="2477" height="1856" alt="Animetta screenshot" src="https://github.com/user-attachments/assets/8b3cb1f7-ef61-4cb0-b702-546b3aa8e65e" />

Animetta is an open-source framework for building **AI virtual companions and VTubers** — characters that talk, listen, remember, emote through a Live2D avatar, and act in the world (chat, livestream, Minecraft). It orchestrates ASR → LLM → TTS → emotion as a single LangGraph state machine, so every turn can branch, call tools, and resume.

> **Why Animetta?** Most "AI VTuber" projects hardcode one provider pipeline. Animetta makes every layer — LLM, ASR, TTS, VAD, memory, tools — a swappable plugin via `@ProviderRegistry`, with full observability built in.

## Contents

- [Highlights](#-highlights)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Core Modules](#-core-modules)
- [Project Structure](#-project-structure)
- [Extending](#-extending)
- [Documentation](#-documentation)
- [Contributing](#-contributing)
- [Tech Stack](#-tech-stack)
- [License](#-license)

---

## ✨ Highlights

Animetta is not just another "ChatGPT + TTS" glue. It is an **engineered AI companion framework** built around three principles: **configurable, observable, extensible**.

- **LangGraph state-graph orchestration** — not a linear pipeline, but a directed graph with conditional routing, tool-calling loops, and interrupt/resume.
- **Plugin provider architecture** — register new vendors via the `@ProviderRegistry` decorator, zero core-code intrusion.
- **Hybrid memory system** — Chroma vector search (70%) + SQLite FTS5 keyword match (30%) + Markdown wiki knowledge base.
- **Live2D emotion-driven** — LLM output → emotion analysis → Live2D parameter mapping; expressions change in real time with the conversation.
- **Full-chain observability** — OpenTelemetry distributed tracing + Prometheus metrics + built-in Stats Dashboard.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Frontend (Vue 3 + Vite)                      │
│               Live2D Renderer · Chat UI · Stats Dashboard         │
└─────────────────────────────┬────────────────────────────────────┘
                              │ Socket.IO / REST
┌─────────────────────────────▼────────────────────────────────────┐
│                WebSocket Server (Starlette + Socket.IO ASGI)      │
│               Session Mgmt · Desktop App · Live2D Events          │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                   LangGraph Orchestration Engine                   │
│                                                                   │
│  ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ ASR Node│ → │ Persona │ → │ LLM Node │ → │ Emotion Node │    │
│  │         │   │  Node   │   │  + RAG   │   │ → Live2D Map │    │
│  └─────────┘   └─────────┘   └────┬─────┘   └──────────────┘    │
│                                  │                                │
│                          ┌───────▼───────┐   ┌─────────────┐     │
│                          │  Tool Node   │   │ Output Node │     │
│                          │ MC/MCP/Custom│   │TTS + Memory │     │
│                          └──────────────┘   └─────────────┘     │
└───────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Services    │   │    Memory     │   │   Tracing     │
│ LLM/ASR/TTS   │   │Chroma+SQLite  │   │ OTel + Stats  │
│ Live2D / VAD  │   │+ Wiki + Meme  │   │+ Prometheus   │
└───────────────┘   └───────────────┘   └───────────────┘
```

> Deeper architecture detail: [docs/architecture/overview.md](docs/architecture/overview.md).

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.13** (the toolchain targets 3.13 via ruff/mypy)
- **Node.js 20+** and **pnpm** (frontend)
- _(optional)_ NVIDIA GPU + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for GPU mode

### 1. Install dependencies

```bash
pip install -r requirements.txt
cd frontend && pnpm install
```

### 2. Configure

Edit `config/animetta.yaml` to choose the persona and the complete provider map for the `test`, `smoke`, and `production` profiles. Provider selection lives only in this manifest; environment variables supply profile, endpoints, and secrets.

```bash
cp .env.example .env
# Choose test, smoke, or production and fill only the keys it needs:
#   ANIMETTA_PROFILE="test"
#   DEEPSEEK_API_KEY="..."
#   MIMO_API_KEY="..."
#   QWEN_TTS_API_KEY="..."
```

### 3. Run

```bash
# Backend
python -m animetta.core.socketio_server

# Frontend (in a second terminal)
cd frontend && pnpm dev
```

The frontend dev server runs on `http://localhost:3000`; the backend on `http://localhost:12394`.

### Docker Compose

```bash
# GPU mode (recommended when an NVIDIA GPU is available)
# One-time Qwen deployment, or after changing its image/model contract
python scripts/runtime_lifecycle.py qwen-deploy

# Routine startup: validates Qwen, then builds/starts only Animetta
python scripts/runtime_lifecycle.py anima-up

# CPU mode (no GPU)
docker compose -f docker-compose.cpu.yml up -d --build
```

Routine `python scripts/runtime_lifecycle.py anima-down` leaves the Qwen worker and
its loaded model running. Use the `qwen-stop` operation only when GPU memory must be
released. Equivalent `make` aliases are available on systems that provide Make.

Once healthy, the frontend is served by nginx on **port 80** and the backend health endpoint is at `http://localhost:12394/health` (also proxied at `http://localhost/health`).

> Full deployment guides: [Docker](docs/deployment/docker.md) · [Zeabur](docs/deployment/zeabur.md)

---

## 🔧 Core Modules

| Module | What it does | Docs |
|--------|--------------|------|
| **LangGraph engine** | Directed-graph orchestration with conditional routing, tool loops, interrupt/resume | [docs/architecture/overview.md](docs/architecture/overview.md) |
| **Provider plugins** | Register LLM/ASR/TTS/VAD/Singing vendors via `@ProviderRegistry` | [docs/reference/tools.md](docs/reference/tools.md) |
| **Hybrid memory** | Chroma (70%) + SQLite FTS5 (30%) + Markdown wiki + meme learner | ADR-002, ADR-005 |
| **Live2D emotion** | LLM → emotion tag → Live2D param mapping (6 base emotions) | ADR-009 |
| **Minecraft bot** | Mineflayer-based bot, decoupled external Voyager runtime | [docs/development/minecraft-bot-architecture.md](docs/development/minecraft-bot-architecture.md) |
| **Observability** | OpenTelemetry traces + Prometheus metrics + Stats Dashboard | ADR-006 |

**Supported providers:**

| Type | Providers |
|------|-----------|
| **LLM** | OpenAI · GLM (Zhipu) · Ollama · DeepSeek · Mock |
| **ASR** | OpenAI Whisper · GLM ASR · Mock |
| **TTS** (core) | Edge · MiMo · Qwen3 · GPT-SoVITS · Mock |
| **TTS** (contrib) | GLM · ChatTTS · Kokoro · VibeVoice |
| **VAD** | Silero VAD |

> Socket.IO event catalog and API reference live in [docs/reference/](docs/reference/).

---

## 📁 Project Structure

```
animetta/
├── src/animetta/          # Python backend (Starlette + LangGraph + Socket.IO)
│   ├── core/              # Entry point + service container
│   ├── orchestration/     # LangGraph state graph + WebSocket server
│   ├── services/          # LLM / ASR / TTS / VAD / Singing / Meme / Live2D
│   ├── memory/            # V2 atom-based memory (Chroma + SQLite FTS5)
│   ├── tools/             # Tool calling + MCP bridge + Minecraft bot
│   ├── avatar/            # Live2D emotion/expression analysis
│   ├── config/            # Pydantic configs + provider registry
│   ├── tracing/           # OpenTelemetry observability
│   ├── notifier/          # Alert channels (Discord, Feishu, Email)
│   ├── inspection/        # Health / telemetry background checks
│   └── acceptance/        # Golden soak state machine
├── frontend/              # Vue 3 + TypeScript + Vite (Electron desktop)
├── config/                # YAML config files (personas, services, tools)
├── design-system/         # Visual design spec (HTML spec sheets)
├── docs/                  # Architecture, ADRs, deployment, references
├── tests/                 # pytest (backend) + vitest (frontend)
└── openspec/              # Spec-driven change tracking
```

---

## 🧩 Extending

**Add a provider** (LLM/ASR/TTS/VAD):

```python
# 1. Create a config class
@ProviderRegistry.register("llm", "my_llm")
class MyLLMConfig(BaseLLMConfig):
    api_key: str

# 2. Register the service
@ProviderRegistry.register_service("llm", "my_llm")
class MyLLMAgent(AgentInterface):
    @classmethod
    def from_config(cls, config, **kwargs):
        return cls(api_key=config.api_key)
```

**Add a graph node** — follow the node pattern in [`src/animetta/orchestration/graph/`](src/animetta/orchestration/graph/).

**Add a tool** — use the `@tool` decorator in [`src/animetta/tools/`](src/animetta/tools/).

> Agent conventions (for ZCode / Claude Code / Cursor): see [AGENTS.md](AGENTS.md).

---

## 📚 Documentation

| Topic | Location |
|-------|----------|
| Architecture overview | [docs/architecture/overview.md](docs/architecture/overview.md) |
| Architecture Decision Records (13) | [docs/adrs/](docs/adrs/) |
| Backend & Socket.IO API reference | [docs/reference/](docs/reference/) |
| Testing guide | [docs/development/testing.md](docs/development/testing.md) |
| Deployment (Docker / Zeabur) | [docs/deployment/](docs/deployment/) |
| Design system | [design-system/](design-system/) |
| Doc navigation index | [docs/README.md](docs/README.md) |

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code standards, and test commands. New changes are tracked via the [openspec](openspec/) spec-driven system — run `/opsx-propose` to start a change.

---

## 📊 Tech Stack

| Layer | Technology |
|-------|------------|
| **Orchestration** | LangGraph · LangChain |
| **Backend** | Starlette · Socket.IO ASGI |
| **Frontend** | Vue 3 · Vite · TypeScript · Pinia · UnoCSS · pixi.js · Live2D Cubism SDK · Electron |
| **Memory** | ChromaDB · SQLite FTS5 · Markdown Wiki |
| **Tracing** | OpenTelemetry · Prometheus · Langfuse |
| **AI** | OpenAI · Zhipu GLM · DeepSeek · Ollama · Whisper · Qwen3-TTS · GPT-SoVITS |
| **Audio** | Demucs · GPT-SoVITS · RVC · yt-dlp |
| **Game** | Mineflayer (Node.js) |

---

## 📄 License

[MIT License](LICENSE) — Copyright (c) 2026 Cowork

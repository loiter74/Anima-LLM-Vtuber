# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Animetta is a configurable AI virtual companion / VTuber framework with Live2D avatar support. It features:
- Plugin-based architecture with decorator-based service registration
- Profile-driven configuration (switch between LLM/ASR/TTS providers)
- LangGraph state graph for dialogue orchestration
- Streaming response support for LLM and TTS
- Memory system with hybrid vector+keyword search for long-term context
- Tool calling support with MCP protocol integration

## Commands

### Running the Application

#### Docker (Recommended)
```bash
# GPU deployment (default)
docker compose up -d --build

# CPU-only (no GPU)
docker compose -f docker-compose.cpu.yml up -d --build

# Check health
curl -s http://localhost/health

# View logs
docker compose logs -f animetta

# Stop
docker compose down
```

#### Local Development (Alternative)
```bash
# Backend only
PYTHONPATH=src python -m animetta.core.socketio_server

# Frontend only (from frontend/)
cd frontend && pnpm dev
```

### Docker (Production)
```bash
# GPU deployment
docker compose up -d --build

# CPU-only
docker compose -f docker-compose.cpu.yml up -d --build

# Logs / shell
docker compose logs -f animetta
docker compose exec animetta bash
```

### Development
```bash
# Backend
pip install -r requirements.txt

# Frontend (from frontend/)
cd frontend && pnpm install
pnpm dev              # Dev server on port 3000 (proxies to backend)
pnpm build            # Production build
pnpm typecheck        # TypeScript type checking
```

### Testing
```bash
# Backend tests
PYTHONPATH=src python -m pytest                          # All fast tests (parallel, skip slow)
PYTHONPATH=src python -m pytest tests/test_foo.py        # Single test file
PYTHONPATH=src python -m pytest tests/test_foo.py -k foo # Single test by name
PYTHONPATH=src python -m pytest -m integration           # Integration tests only
PYTHONPATH=src python -m pytest -m slow                  # Slow tests only

# Frontend tests (from frontend/)
pnpm test              # Vitest watch mode
pnpm test:run          # Vitest single run
pnpm test:coverage     # With coverage
```

### Linting & Type Checking
```bash
# Backend
PYTHONPATH=src python -m ruff check src/           # Lint
PYTHONPATH=src python -m ruff format src/          # Format
PYTHONPATH=src python -m mypy src/animetta/        # Type check

# Frontend
cd frontend && pnpm typecheck
```

## Architecture

### Backend (Python/FastAPI/Socket.IO)

```
src/animetta/
├── core/                          # Core runtime
│   ├── socketio_server.py         # Main entry point, WebSocket server
│   ├── service_context.py         # Service container (ASR/TTS/LLM/VAD/memory)
│   └── service_pool.py            # Service instance pooling
├── orchestration/                 # LangGraph state graph
│   ├── graph/
│   │   ├── state.py               # AgentState definition
│   │   ├── builder.py             # StateGraph builder + compile
│   │   ├── orchestrator.py        # LangGraphOrchestrator
│   │   ├── tool_manager.py        # Tool registration & lifecycle
│   │   ├── personality_node.py    # Personality/mood processing
│   │   ├── llm_node.py            # LLM reasoning (RAG + tools)
│   │   ├── asr_node.py            # Speech recognition
│   │   ├── tts_node.py            # Speech synthesis
│   │   ├── emotion_node.py        # Emotion analysis
│   │   ├── tool_node.py           # Tool execution
│   │   ├── vc_node.py             # Voice conversion
│   │   ├── output_node.py         # Output to frontend + memory storage
│   │   ├── node_error.py          # Error handling
│   │   └── memory_middleware.py   # Memory integration
│   └── server/
│       ├── session.py             # Session management
│       ├── websocket.py           # WebSocket handlers
│       ├── routes.py              # HTTP routes
│       ├── lifecycle.py           # Server startup/shutdown
│       └── handlers/              # Feature-specific handlers
│           ├── chat_handlers.py
│           ├── live2d_handlers.py
│           ├── singing_handlers.py
│           ├── minecraft_handlers.py
│           ├── bilibili_handlers.py
│           ├── persona_handlers.py
│           ├── config_handlers.py
│           └── lifecycle_handlers.py
├── config/                        # Configuration (YAML + Pydantic V2)
│   ├── app.py                     # AppConfig - main configuration
│   ├── agent.py                   # AgentConfig
│   ├── persona/                   # Character personality configs
│   ├── providers/                 # Provider configs (asr/tts/llm/vad/vc/separation)
│   ├── live2d.py                  # Live2D configuration
│   └── core/registry.py           # ProviderRegistry (plugin decorators)
├── services/                      # Service implementations
│   ├── asr/                       # Speech recognition (FasterWhisper, FunASR, OpenAI, GLM)
│   ├── tts/                       # Speech synthesis (Edge TTS, Kokoro, OpenAI, GLM)
│   ├── llm/                       # Language models (GLM, OpenAI, DeepSeek, Ollama, LocalLoRA)
│   ├── vad/                       # Voice activity detection (Silero)
│   ├── vc/                        # Voice conversion (RVC)
│   ├── live2d/                    # Live2D action queue, viseme sync, preset loader
│   ├── audio/                     # Audio processing
│   ├── separation/                # Audio separation (Demucs)
│   ├── singing/                   # Singing synthesis (lyrics, mixer, RVC bridge)
│   ├── live/                      # Live streaming services
│   └── meme/                      # Meme generation & collection (Bilibili)
├── memory/                        # Conversation memory
│   ├── v2/                        # LivingMemorySystem (atom-based, current)
│   │   ├── system.py              # LivingMemorySystem main
│   │   ├── atom.py                # Memory atoms
│   │   ├── compile.py             # Memory compilation
│   │   ├── metabolism.py          # Memory metabolism
│   │   ├── reconsolidation.py     # Memory reconsolidation
│   │   ├── emotion_field.py       # Emotion field
│   │   ├── store.py               # Storage layer
│   │   └── search.py              # Hybrid search
│   └── wiki/                      # Wiki-based memory (Markdown source of truth)
├── avatar/                        # Live2D expression analysis
│   ├── analyzers/                 # Keyword/LLM/audio-based emotion extraction
│   ├── strategies/                # Duration, intensity, position-based strategies
│   └── mappers/                   # Emotion-to-parameter mapping
├── tools/                         # Tool calling system
│   ├── base.py                    # Built-in tools
│   ├── config.py                  # Tool configuration loader
│   ├── mcp_bridge.py              # MCP protocol bridge
│   ├── langchain_tools.py         # LangChain tool wrappers
│   └── minecraft/                 # Minecraft bot integration
├── notifier/                      # Notification system (Discord, Feishu, Email)
├── inspection/                    # Pipeline inspection & health checks
├── tracing/                       # OpenTelemetry tracing
└── utils/                         # Helpers (env, logging, auto-config)
```

### Frontend (Vue 3 + Vite + TypeScript)

Web application (not Electron). Connects to backend via Socket.IO on port 12394.

```
frontend/
├── src/
│   ├── components/
│   │   ├── chat/                  # ChatPanel, MessageList, InputBar, VoiceButton
│   │   ├── live2d/                # Live2DRenderer (pixi.js + pixi-live2d-display)
│   │   ├── dashboard/             # Stats, charts, performance monitoring
│   │   ├── layout/                # AppLayout, TitleBar
│   │   └── shared/                # GlassPanel, AnimatedButton
│   ├── composables/               # useSocket, useChat, useVoice, useLive2D, useAudio, useSinging, useDanmaku
│   ├── stores/                    # Pinia stores (chat, connection, memory, singing, personality, dashboard)
│   ├── types/                     # TypeScript types (chat, live2d, socket-events, singing)
│   ├── views/                     # Page components (chat, dashboard, meme-review, music)
│   ├── router/                    # Vue Router (memory history, lazy-loaded routes)
│   └── styles/                    # Global styles + animations
├── public/
│   ├── live2d/                    # Live2D models + Cubism Core
│   └── avatar/                    # Avatar images
├── vite.config.ts                 # Vite config (proxy to backend :12394)
├── vitest.config.ts               # Test config (happy-dom)
├── uno.config.ts                  # UnoCSS (anime theme tokens, glassmorphism)
└── package.json
```

### Data Flow (LangGraph)

```
[START] → route_input()
    │
    ├── (audio) → [asr_node]
    │                  │
    └── (text) ────────┴──→ [personality_node]
                                │
                           [llm_node]
                                │
                       ┌────────┴────────┐
                       │                 │
                 (tool_calls)     (direct reply)
                       │                 │
                  [tool_node]       [tts_node]
                       │                 │
                       └────→ [llm] ←────┘   (tool loop)
                                │
                           [emotion_node]
                                │
                           [output_node] → Socket.IO → Frontend
                                │
                           Store to memory
                                │
                              [END]
```

## Key Patterns

### AgentState (`orchestration/graph/state.py`)

The central TypedDict passed between nodes. Key fields:
- **Input**: `input_type`, `raw_audio`, `user_text`
- **Conversation**: `messages` (annotated with `add_messages`), `system_prompt`
- **Tools**: `tool_calls`, `tool_results`
- **Output**: `response_text`, `response_chunks`, `tts_audio`, `emotion`, `emotion_vad`
- **Personality**: `personality_mode` (`'default'`|`'streaming'`|`'mood_xxx'`), `personality_mood`
- **Error**: `error`, `should_retry`, `retry_count`
- **Metadata**: `session_id`, `persona`, `channel_id`, `user_id`, `user_name`, `_timings`

Use `create_initial_state()` to construct valid initial state.

### Adding a New Service Provider

1. Create config class in `src/animetta/config/providers/<category>/my_provider.py`
2. Create service in `src/animetta/services/<category>/`
3. Register with decorators:
```python
@ProviderRegistry.register_config("llm", "my_llm")
class MyLLMConfig(LLMBaseConfig):
    type: Literal["my_llm"] = "my_llm"

@ProviderRegistry.register_service("llm", "my_llm")
class MyLLMAgent(LLMInterface):
    @classmethod
    def from_config(cls, config, **kwargs):
        return cls(api_key=config.api_key, model=config.model)
```

Categories: `"llm"`, `"asr"`, `"tts"`, `"vad"`

### Adding a New Graph Node

1. Create node module in `src/animetta/orchestration/graph/my_node.py`
2. Import in `builder.py`, add `graph.add_node("my_node", my_node)`
3. Wire edges: `graph.add_edge("prev_node", "my_node")`
4. Nodes access services via `ConfigStore.get(session_id, "service_context")`

### ConfigStore Pattern

Nodes can't receive all data through LangGraph's config. Use ConfigStore:
```python
from animetta.orchestration.graph.config_store import ConfigStore

# Set (in orchestrator)
ConfigStore.set(session_id, "service_context", service_context)

# Get (in node)
service_context = ConfigStore.get(state["session_id"], "service_context")
```

### Tool Registration

```python
from langchain_core.tools import tool

@tool
async def my_tool(param: str) -> str:
    """Tool description for LLM."""
    return f"Result: {param}"
```

Tools are loaded via `config/tools.yaml` and registered in `tool_manager.py`.

## Configuration

### Main Config (`config/config.yaml`)
```yaml
persona: "neuro-vtuber"
services:
  asr: faster_whisper
  tts: edge
  agent: glm
  local_llm: local_lora
  vad: silero
system:
  host: "0.0.0.0"
  port: 12394
```

### Other Config Files
- `config/services.yaml` — Detailed provider configurations
- `config/tools.yaml` — Built-in tools, MCP servers, Minecraft settings
- `config/personas/` — Character personality definitions
- `config/singing.yaml` — Singing synthesis config
- `config/observability.yaml` — Tracing/metrics config
- `.env` — API keys (see `.env.example`)

## WebSocket Events

**Client → Server:**
- `text_input` — `{text, from_name?}`
- `raw_audio_data` — `{audio: float32[]}` (VAD mode)
- `mic_audio_end` — Signal end of audio
- `interrupt_signal` — `{heard_text?}`

**Server → Client:**
- `text` — `{text, seq}` (streaming chunks)
- `audio` — `{data: base64, format}`
- `audio_with_expression` — `{audio_path, text, emotions, volumes}`
- `expression` — `{expression}`
- `control` — `{signal}` (conversation-start/end, interrupt)
- `transcript` — `{text, is_final}`

## Ports

- Backend: 12394 (Socket.IO + FastAPI)
- Frontend dev: 3000 (Vite, proxies to backend)
- Docker nginx: 80 (serves frontend + proxies to backend)

## Containerization Conventions

**Key files:**
- `Dockerfile.cuda` — Multi-stage build (frontend builder → Python deps → CUDA 12.4 runtime)
- `docker-compose.yml` — GPU deployment with NVIDIA runtime
- `docker-compose.cpu.yml` — CPU-only fallback
- `docker/nginx.conf` — Reverse proxy config (WebSocket + API + static files)
- `docker/entrypoint.sh` — Starts nginx + backend, handles SIGTERM gracefully

**Volumes:** `animetta-memory-db` (`/app/memory_db`), `animetta-data` (`/app/data`). Both use named volumes for persistence.

**TTS:** Default is `vibe_voice`. `edge-tts` has been removed from requirements and is no longer available as a provider. Use `kokoro` or `openai` as alternatives.

**When modifying Docker config:** Always test `docker compose build` succeeds and `curl http://localhost/health` returns ok after `docker compose up -d`.

## Testing Conventions

- **pytest** with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- **Markers**: `@pytest.mark.integration` (external services), `@pytest.mark.slow` (skipped by default)
- **Parallel**: `-n auto` enabled by default via pytest-xdist
- **Coverage**: `--cov=src/animetta` (target tracked in CI)
- **Frontend**: Vitest with happy-dom, `@testing-library/vue`

## Code Style

- **Python**: Ruff (target 3.13, line-length 100, rules E/F/I/N/W/UP/SIM). Double quotes.
- **TypeScript**: vue-tsc strict checking, UnoCSS for styling
- **Async-first**: All service methods are async. Use `asyncio_mode = "auto"` in tests.

## Related Documentation

- [AGENTS.md](AGENTS.md) — Detailed "where to look" guide for different tasks
- [docs/TOOLS.md](docs/TOOLS.md) — Tools system guide
- [docs/ADR/](docs/ADR/) — Architecture Decision Records

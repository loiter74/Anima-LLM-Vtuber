# ANIMA BACKEND — PYTHON PACKAGE

**Generated:** 2026-05-31
**Commit:** cdd4a5f

> Parent: [../AGENTS.md](../AGENTS.md) — root project conventions and anti-patterns.

## OVERVIEW
Python backend for Anima VTuber — Starlette + LangGraph + Socket.IO ASGI orchestration with plugin-based provider architecture. ~423 files, 30K+ lines, max depth 3.

## STRUCTURE
```
src/animetta/
├── core/                    # Process entry point + one-release runtime import facades
├── runtime/                 # Provider/session/checkpoint/readiness lifecycle ownership
├── orchestration/           # → see orchestration/AGENTS.md
│   ├── graph/               # LangGraph nodes + orchestrator
│   └── server/              # WebSocket routes + sessions
├── services/                # → see services/AGENTS.md (FLAT — no speech/ or intelligence/)
│   ├── llm/                 # Language models (deepseek, openai, glm, ollama, local_lora)
│   ├── asr/                 # Speech recognition (funasr, faster_whisper, glm, mock)
│   ├── tts/                 # Text-to-speech (core/contrib layered, 9 providers)
│   ├── vad/                 # Voice activity detection (silero, mock)
│   ├── vc/                  # Voice conversion (RVC, mock)
│   ├── separation/          # Audio source separation (Demucs, mock)
│   ├── audio/               # Audio processing pipeline
│   ├── live2d/              # Live2D action queue + viseme sync
│   ├── singing/             # RVC/SVC singing pipeline
│   ├── live/                # Bilibili danmaku livestream
│   └── meme/                # Meme pattern detection
├── memory/                  # → see memory/AGENTS.md (V2 atom-based)
│   └── v2/                  # AtomStore + CompileEngine + Metabolism
├── config/                  # Pydantic configs (YAML-driven)
│   ├── providers/{llm,asr,tts,vad,vc,separation}/  # Provider config classes
│   ├── persona/             # Character personality configs
│   └── core/registry.py     # @ProviderRegistry decorator
├── avatar/                  # Live2D emotion/expression analysis
│   ├── analyzers/           # Keyword + LLM-based emotion extraction
│   ├── mappers/             # Emotion → Live2D parameter mapping
│   └── strategies/          # Duration/intensity/position strategies
├── tools/                   # Tool calling + MCP bridge + game-bot/Minecraft adapters
│   ├── gamebot/             # Generic game-bot contracts/client/stdio transport
│   └── minecraft/           # Minecraft-specific Python adapters and orchestration
├── notifier/                # Alert channels (Discord, Feishu, Email)
├── inspection/              # Health/telemetry background checks
├── tracing/                 # OpenTelemetry observability
└── utils/                   # Helpers
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Main server entry | `core/socketio_server.py` | Process bootstrap; delegates ASGI composition to the server package |
| Provider lifecycle | `runtime/provider_pool.py` | Application-owned shared LLM/TTS/ASR engines |
| Session lifecycle | `runtime/session_context.py` | Per-session VAD/memory/audio/emotion dependencies |
| Model loading | `runtime/model_loading.py` | Loads all models, don't block on failures |
| Provider registration | `config/core/registry.py` | `@ProviderRegistry.register_service` decorator |
| App config | `config/app.py` | Main config schema |
| Graph node template | `orchestration/graph/__init__.py` | Node docstring explains pattern |
| Tool definitions | `tools/base.py` + `tools/custom_tools.py` | `@tool` decorator |
| Singing pipeline | `services/singing/` | RVC/SVC pipeline + mixer |
| Minecraft bot | `tools/minecraft/` + `tools/gamebot/` | Anima control plane and Streamable HTTP mc-mcp adapter |
| Health checks | `inspection/` | Background periodic checks |
| Alert notifications | `notifier/` | Discord, Feishu, Email |
| Tracing setup | `tracing/` | OpenTelemetry spans → StatsStore |

## KEY PATTERNS
- **Provider plugin**: `interface.py` ABC → implementations → factory in `__init__.py` → `@ProviderRegistry.register_service`
- **Graph nodes**: Thin state transformers → delegate to `services/`. Never put business logic in nodes.
- **ProviderPool**: One instance per application owns shared engines; sessions own VAD, memory and emotion state
- **ConfigStore**: Workaround for LangGraph config limitation — use `state.get("_config", {})`

## NOTES
- ~423 Python files, 30K+ lines, max depth 3
- `orchestration/server` is the application composition boundary; route modules remain transport adapters
- Services are FLAT (no `speech/` or `intelligence/` nesting)
- Provider configs at `config/providers/{type}/` mirror `services/{type}/`
- Minecraft server, Mineflayer bot and viewer lifecycle belong to independent mc-mcp; Anima communicates only through Streamable HTTP MCP
- Two runtime data dirs: `data/` (chroma_db, stats) + `memory_db/` (chroma_v2, living_memory.sqlite)
- `persistence/` directory deleted — use memory/v2/ directly

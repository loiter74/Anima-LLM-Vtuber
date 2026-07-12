# Unified Model Loading System

## Problem

Models (ASR, TTS, VAD, LLM) have inconsistent loading strategies:

| Service | Loading Strategy | Timing |
|---------|-----------------|--------|
| Silero VAD | Synchronous in constructor | Session creation |
| LocalLoraLLM | Synchronous in constructor | Session creation |
| FasterWhisper ASR | Lazy via `_get_model()` | First `transcribe()` call |
| ChatTTS | Lazy via `_ensure_loaded()` | First `synthesize()` call |
| GLM/OpenAI LLM | Lazy client creation | First API call |
| EdgeTTS | No local model | N/A |

This causes:
- **First-message latency**: user waits for models to load on first conversation
- **Race condition**: ASR background preload may not finish before first audio input
- **No visibility**: frontend has no idea what's loading
- **No cross-session sharing**: each session re-loads the same models
- **No startup pre-warming**: server starts with zero model loading

## Design: ModelLoadingManager

### Architecture

```
src/animetta/core/
├── model_loading_manager.py    # NEW: central loading orchestration
├── service_context.py          # MODIFIED: uses manager instead of ad-hoc loading
└── socketio_server.py          # MODIFIED: calls warmup() at startup

src/animetta/services/
├── speech/asr/faster_whisper_asr.py    # MODIFIED: preload() returns immediately if already loaded
├── speech/tts/chattts_tts.py            # MODIFIED: add preload() method
├── intelligence/vad/silero_vad.py       # MINOR: extract model loading to preload()
├── intelligence/llm/local_lora_llm.py   # MINOR: already loads eagerly, just adapt interface
└── intelligence/llm/glm_llm.py          # MINOR: add lightweight preload()
```

### ModelLoadingManager API

```python
class ModelLoadState(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"

class ModelLoadingManager:
    """
    Centralized manager that coordinates model loading lifecycle.

    Usage:
        manager = ModelLoadingManager(socketio=sio)

        # Register services with their loader functions
        manager.register("asr", faster_whisper_engine)
        manager.register("vad", silero_vad_engine)
        manager.register("tts", chattts_engine)

        # Warm up at server startup (non-blocking)
        await manager.warmup()

        # Get a model instance (awaits if still loading)
        asr = await manager.get("asr")

        # Check overall status
        status = manager.get_status()
        # Returns: {"asr": "loaded", "vad": "loading", "tts": "unloaded"}
    """

    def __init__(self, socketio=None):
        self._models: Dict[str, ModelSlot] = {}
        self._socketio = socketio

    def register(
        self,
        name: str,
        service: Any,
        preload_fn: Optional[Callable] = None,
    ) -> None:
        """Register a service for lifecycle management."""

    async def warmup(self) -> None:
        """
        Start preloading ALL registered models in background.
        Non-blocking: returns immediately, models load concurrently.
        """

    async def get(self, name: str, timeout: float = 30.0) -> Any:
        """
        Get a model instance. If still loading, await until ready.
        Raises TimeoutError if model fails to load within timeout.
        """

    def get_status(self) -> Dict[str, str]:
        """Return all models' loading states."""

    async def wait_all(self, timeout: float = 60.0) -> bool:
        """Wait until all registered models are loaded."""
```

### Event Flow

```
Server startup
  │
  ├── socketio_server.run_server()
  │     └── create_server(config)
  │           └── server.start()
  │                 └── model_manager.warmup()
  │                       │
  │                       ├── asr:     set LOADING → emit event → load → set LOADED → emit event
  │                       ├── vad:     set LOADING → emit event → load → set LOADED → emit event
  │                       ├── tts:     set LOADING → emit event → load → set LOADED → emit event
  │                       └── llm:     set LOADING → emit event → load → set LOADED → emit event
  │
  └── (warmup runs concurrently, server is already accepting connections)

User connects
  │
  └── on_text_input → get_or_create_context
        └── ServiceContext.load_from_config()
              ├── Models may already be loaded (if warmup finished)
              │     → Zero wait time, just attach references
              └── Models may still be loading (warmup in progress)
                    → await manager.get("asr") → returns when done

User sends first message
  → All models ready → No loading latency
```

### Socket.IO Events (Frontend Progress)

```json
// Server → Client
{
  "type": "model_loading_status",
  "models": {
    "asr":  { "status": "loading", "progress": 0.3 },
    "vad":  { "status": "loaded",  "progress": 1.0 },
    "tts":  { "status": "unloaded", "progress": 0.0 },
    "llm":  { "status": "loading", "progress": 0.6 }
  },
  "overall_progress": 0.475
}
```

### Implementation Plan

**Phase 1: Core Manager**
1. Create `ModelLoadingManager` class with register/warmup/get/get_status
2. Integrate into `WebSocketServer` lifecycle
3. Add Socket.IO event emission for loading progress

**Phase 2: Service Adaptation**
4. `FasterWhisperASR` - make `preload()` idempotent (skip if already loaded)
5. `ChatTTS` - add `preload()` method matching existing pattern
6. `SileroVAD` - extract model loading to support preload pattern
7. `GLMLLM` - add lightweight preload for client initialization
8. Register all services with `ModelLoadingManager`

**Phase 3: Session Integration**
9. Modify `ServiceContext.load_from_config()` to use `manager.get()` instead of direct init
10. Remove ad-hoc `_preload_asr_background()` (replaced by manager.warmup())
11. Add `warmup()` call to server startup

**Phase 4: Frontend (Optional)**
12. Add model loading status indicator to frontend UI

### Testing

- Unit test: `ModelLoadingManager` register/warmup/get/get_status
- Unit test: concurrent warmup + get with timeout
- Unit test: error handling (model fails to load)
- Integration: full startup sequence with real model manager
- Integration: first-message timing measurement

### Non-Goals

- Model instance sharing across sessions (future concern)
- GPU memory pooling
- Dynamic model switching at runtime (already handled by existing config switch)

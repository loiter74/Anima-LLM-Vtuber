# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Backend (Python)
```bash
# Start the Socket.IO server (main entry point)
python -m anima.socketio_server

# Start with custom config file
python -m anima.socketio_server path/to/config.yaml

# Install dependencies
pip install -r requirements.txt
```

### Frontend (Next.js)
```bash
cd frontend
pnpm dev        # Start dev server
pnpm build      # Build for production
pnpm start      # Start production server
pnpm lint       # Run ESLint
```

### Startup Scripts
- `scripts/start.sh` - Unix startup script (starts both backend and frontend)
- `scripts/start.bat` - Windows batch startup script
- `scripts/start.ps1` - PowerShell startup script (recommended on Windows)
- `scripts/stop.bat` / `scripts/stop.ps1` - Stop scripts

All scripts support options:
- `--skip-backend` / `--skip-frontend` - Start only one service
- `--install` - Reinstall dependencies before starting
- `--help` - Show help information

**Quick start (Windows):**
```powershell
# PowerShell
.\scripts\start.ps1

# Or with dependency reinstall
.\scripts\start.ps1 --install
```

**Quick start (Unix/macOS):**
```bash
./scripts/start.sh
```

## Architecture Overview

Anima is a modular AI VTuber framework with a plugin-based architecture. The system follows a **pipeline + event-driven** pattern with three main layers:

```
WebSocket Server → ConversationOrchestrator → Pipeline System → EventBus → Handlers
                      ↓
                ServiceContext (ASR/TTS/LLM/VAD)
```

### Conversation Flow

1. **Input** (text or audio) → `InputPipeline` (ASR → TextClean)
2. **Processing** → `Agent.chat_stream()` yields streaming chunks
3. **Output** → `OutputPipeline` converts chunks to `OutputEvent`s
4. **Distribution** → `EventBus` → `EventRouter` → registered `Handler`s
5. **Response** → Handlers send messages via WebSocket

### Core Architecture Components

**1. ConversationOrchestrator (`src/anima/services/conversation/orchestrator.py`)**
- Central coordinator integrating ASR, TTS, Agent, and EventBus
- Each session gets its own orchestrator instance
- Manages the complete conversation lifecycle: `process_input()` → `_process_conversation()`
- Auto-assembles default pipeline steps (ASRStep, TextCleanStep)
- Handles interruption via `interrupt()` method
- Returns `ConversationResult` with response_text, audio_path, error

**2. ServiceContext (`src/anima/service_context.py`)**
- Service container holding ASR, TTS, LLM, and VAD engine instances
- VAD (Voice Activity Detection) options: `silero` (Silero VAD model), `mock`
- **VAD System**: Automatically detects speech in audio stream, triggers ASR when silence detected
  - Silero VAD: Uses pre-trained torch model for voice activity detection
  - Mock VAD: Always returns true (useful for testing)
- Lazy initialization - services loaded via `load_from_config(AppConfig)`
- Services use factory pattern: `AgentFactory.create_from_config()`
- Lifecycle management: `async def close()` cleans up all resources

**3. Pipeline System (`src/anima/pipeline/`)**
- Chain-of-responsibility pattern for data processing

**InputPipeline** (`input_pipeline.py`):
- Processes user input before Agent
- Default steps: `ASRStep` (audio→text) → `TextCleanStep`
- Each step receives and modifies `PipelineContext`

**OutputPipeline** (`output_pipeline.py`):
- Processes Agent streaming response
- Iterates through `chat_stream()` AsyncIterator
- Emits `OutputEvent`s to EventBus for each chunk
- Sends completion marker (empty text event) when streaming finishes
- Handles interruption via `interrupt()` method

**PipelineContext** (`src/anima/core/context.py`):
- Data carrier passed through pipeline steps
- Fields: `raw_input`, `text`, `response`, `metadata`, `error`, `skip_remaining`

**4. EventBus + EventRouter (`src/anima/eventbus/`)**
- Decouples pipeline from handlers via pub/sub

**EventBus** (`bus.py`):
- Core pub/sub mechanism with priority support
- Methods: `subscribe(event_type, handler, priority)`, `emit(event)`, `unsubscribe(sub)`
- Returns `Subscription` objects for management
- Exception isolation: one handler failure doesn't affect others

**EventRouter** (`router.py`):
- Routes events to specific Handler instances
- Wraps handlers with exception isolation
- Methods: `register(event_type, handler)`, `setup()`, `clear()`
- Chain-able: `router.register("sentence", handler).register("audio", handler)`

**5. Handler System (`src/anima/handlers/`)**
- Base class: `BaseHandler` with `async def handle(event: OutputEvent)`
- Auto-registered via EventRouter
- Receive WebSocket send function in constructor
- Emit via `self.send(message_dict)`

**Available Handlers**:
- `TextHandler` - Emits text chunks via WebSocket
- `SocketEventAdapter` - Adapts backend events to frontend format
  - Maps event names: `sentence` → `text`, `user-transcript` → `transcript`
  - Adds missing fields for frontend compatibility
  - Can be disabled via `enable_adapter=False`

**6. Provider Registry (`src/anima/config/core/registry.py`)**
- Decorator-based plugin system
- `@ProviderRegistry.register_config("llm", "openai")` - registers config class
- `@ProviderRegistry.register_service("llm", "openai")` - registers service class
- Supports discriminated unions for type-safe config loading

## Configuration System

### Supported Services

| Type | Providers |
|------|-----------|
| LLM | OpenAI, GLM (智谱 AI), Ollama, Mock |
| ASR | OpenAI Whisper, GLM ASR, Mock |
| TTS | OpenAI TTS, GLM TTS, Edge TTS, Mock |
| VAD | Silero VAD, Mock |

**GLM (智谱 AI) Integration:**
- The project heavily uses GLM services for LLM, ASR, and TTS
- Uses `zai-sdk` (custom SDK for GLM APIs)
- Configuration files: `config/services/llm/glm.yaml`, `config/services/asr/glm.yaml`, `config/services/tts/glm.yaml`
- Environment variable: `GLM_API_KEY` or `LLM_API_KEY`

### Modular Service Configuration

Services are configured as separate YAML files under `config/services/`:

```
config/
├── config.yaml              # Main config
├── services/
│   ├── asr/
│   │   ├── openai.yaml
│   │   ├── glm.yaml
│   │   └── mock.yaml
│   ├── tts/
│   ├── agent/
│   └── vad/
└── personas/                # Character/persona configs
    ├── default.yaml
    └── neuro-vtuber.yaml
```

In `config/config.yaml`:
```yaml
services:
  asr: glm      # Loads config/services/asr/glm.yaml
  tts: glm
  agent: glm
  vad: mock

persona: "neuro-vtuber"
```

### Persona System

Personas define the AI's character and system prompt:
- Located in `config/personas/`
- Referenced by `persona` field in config.yaml
- Built into system prompt via `app_config.get_system_prompt()`
- Fields: name, description, system_prompt, greeting, etc.

### Adding a New Service Provider

**Step 1: Create config class** (`src/anima/config/providers/llm/my_provider.py`):
```python
from anima.config.core.registry import ProviderRegistry

@ProviderRegistry.register_config("llm", "my_provider")
class MyProviderConfig(LLMBaseConfig):
    type: Literal["my_provider"] = "my_provider"
    api_key: str
    model: str = "my-model"
```

**Step 2: Create service implementation** (`src/anima/services/llm/implementations/my_provider.py`):
```python
@ProviderRegistry.register_service("llm", "my_provider")
class MyProviderAgent(LLMInterface):
    @classmethod
    def from_config(cls, config):
        return cls(api_key=config.api_key, model=config.model)

    async def chat_stream(self, text: str) -> AsyncIterator[str | dict]:
        # Yield chunks or {"type": "sentence", "content": "..."}
        yield "response chunk"
```

**Step 3: Create service config** (`config/services/agent/my_provider.yaml`):
```yaml
llm_config:
  type: my_provider
  api_key: "${MY_PROVIDER_API_KEY}"
  model: "my-model"
```

**Step 4: Use in config**:
```yaml
services:
  agent: my_provider
```

## Key Data Structures

**PipelineContext** (`src/anima/core/context.py`)
```python
@dataclass
class PipelineContext:
    raw_input: Union[str, np.ndarray]  # Original input
    text: str                           # Processed text
    response: str                       # Agent response
    metadata: Dict[str, Any]            # Flags like skip_history
    error: Optional[str]                # Error info
    skip_remaining: bool                # Skip further processing
```

**OutputEvent** (`src/anima/core/events.py`)
```python
@dataclass
class OutputEvent:
    type: str          # EventType: SENTENCE, AUDIO, TOOL_CALL, etc.
    data: Any          # Event content
    seq: int           # Sequence number
    metadata: Dict     # Additional info
```

**ConversationResult** (`src/anima/services/conversation/orchestrator.py`)
```python
@dataclass
class ConversationResult:
    success: bool
    response_text: str
    audio_path: Optional[str]
    error: Optional[str]
    metadata: dict
```

## Streaming Patterns

**Agent Response Streaming**:
- Agents must implement `async def chat_stream(text: str) -> AsyncIterator[str | dict]`
- Yield strings for text chunks
- Yield dicts for structured events: `{"type": "tool_call", "content": ...}`
- OutputPipeline consumes this stream and emits events

**Event Types** (`src/anima/core/events.py`):
- `EventType.SENTENCE` - Text chunk
- `EventType.AUDIO` - Audio data
- `EventType.TOOL_CALL` - Function calling
- `EventType.CONTROL` - Control signals
- `EventType.ERROR` - Errors

## Socket.IO Events

**Client → Server:**
- `connect` / `disconnect`
- `text_input` - { text, metadata, from_name }
- `mic_audio_data` - { audio: [] } - Raw audio chunks (for buffered processing)
- `raw_audio_data` - { audio: [] } - For VAD (Voice Activity Detection) processing
- `mic_audio_end` - Triggers conversation processing (signals end of audio input)
- `interrupt_signal` - Interrupt current response

**Audio Input Paths:**
1. **VAD Path**: `raw_audio_data` → VAD engine → auto-detects speech end → `mic_audio_end` → ASR → Agent
2. **Manual Path**: `mic_audio_data` buffers → client sends `mic_audio_end` → ASR → Agent

**Server → Client (before SocketEventAdapter)**:
- `connection-established`
- `sentence` - Streaming text chunks
- `audio` - Audio chunks
- `user-transcript` - ASR result
- `control` - Control signals (start-mic, stop-mic, interrupt, etc.)
- `error`

**Server → Client (after SocketEventAdapter)**:
- `text` - Adapted from `sentence` (frontend expects this)
- `transcript` - Adapted from `user-transcript`
- Other events remain unchanged

## Important Implementation Notes

**Logging**:
- Uses `loguru` for structured logging
- Default log level: INFO (configurable via `system.log_level`)
- Debug logs include session IDs for tracking requests
- Example: `logger.debug(f"[{self.session_id}] Processing input")`

**Session Isolation**:
- Each WebSocket connection gets its own `ServiceContext` and `ConversationOrchestrator`
- Stored in `session_contexts[sid]` and `orchestrators[sid]` dicts
- Cleaned up on disconnect via `cleanup_context(sid)`

**Async/Await**:
- Entire backend is async - use `await` for all I/O
- LLM and TTS return AsyncIterators for streaming

**Interrupt Handling**:
- `ConversationOrchestrator.interrupt()` sets `_interrupted` flag
- Both InputPipeline and OutputPipeline check this flag
- OutputPipeline breaks its async-for loop when interrupted

**Environment Variables**:
- Use `${VAR_NAME}` in YAML configs for API keys
- Supported vars: `LLM_API_KEY`, `ASR_API_KEY`, `TTS_API_KEY`, etc.
- Environment variables can override config values:
  - `LLM_API_KEY` - Overrides LLM API key
  - `LLM_MODEL` - Overrides LLM model
  - `ASR_API_KEY` - Overrides ASR API key
  - `TTS_API_KEY` - Overrides TTS API key

**Factory Pattern**:
- Services created via `Factory.create()` or `Factory.create_from_config()`
- Config classes must have matching `type` field

**Environment Variable Expansion**:
- YAML configs support `${VAR_NAME}` syntax for environment variables
- Example: `api_key: "${GLM_API_KEY}"`
- Expansion happens during config loading via `expand_env_vars()` in `config/app.py`

**Fallback Behavior**:
- `LLMFactory.create_from_config()` falls back to MockAgent if service creation fails
- This prevents crashes when API keys are missing or services are unavailable

**.env Loading**:
- The socketio_server loads `.env` file at startup (before other imports)
- Place `.env` in project root with your API keys

## Frontend Structure

- `app/` - Next.js App Router (`page.tsx` is the main entry point)
- `components/vtuber/` - VTuber-specific components
  - `chat-panel.tsx` - Main chat UI
  - `live-preview.tsx` - Live2D/live video preview
  - `bottom-toolbar.tsx` - Control toolbar
- `components/ui/` - shadcn/ui components (Radix UI + Tailwind)
- `hooks/` - Custom React hooks
  - `use-conversation.ts` - Core conversation state management (2000+ lines, handles all Socket.IO events)
  - `use-mobile.ts` - Mobile detection
  - `use-toast.ts` - Toast notifications
- `lib/socket.ts` - Socket.IO client singleton (wrapper around socket.io-client)
- `contexts/` - React Context providers

**Frontend Development Notes:**
- Uses pnpm as package manager
- Next.js 16 with App Router
- React 19 with TypeScript
- Socket.IO for real-time communication
- shadcn/ui for component library (Radix UI primitives + Tailwind CSS)

## Key Source Directories

```
src/anima/
├── config/                  # Configuration system
│   ├── core/               # Registry, base config classes
│   ├── providers/          # Provider configs (llm/, asr/, tts/, vad/)
│   ├── agent.py            # Agent configuration
│   ├── app.py              # Main AppConfig class
│   ├── persona.py          # Persona configuration
│   └── system.py           # System settings
├── core/                   # Core data structures
│   ├── context.py          # PipelineContext
│   ├── events.py           # EventType, OutputEvent
│   └── types.py            # Type definitions
├── eventbus/               # Event system
│   ├── bus.py              # EventBus (pub/sub)
│   └── router.py           # EventRouter (handler management)
├── pipeline/               # Processing pipelines
│   ├── input_pipeline.py   # Input processing chain
│   ├── output_pipeline.py  # Output processing with streaming
│   └── steps/              # Pipeline steps (ASRStep, TextCleanStep, etc.)
├── services/               # Service implementations
│   ├── llm/                # LLM/Agent services
│   ├── asr/                # ASR services
│   ├── tts/                # TTS services
│   ├── vad/                # VAD services
│   └── conversation/       # ConversationOrchestrator, SessionManager
├── handlers/               # Event handlers
│   ├── base_handler.py     # Base handler class
│   ├── text_handler.py     # Text output handler
│   ├── audio_handler.py    # Audio output handler
│   └── socket_adapter.py   # Socket event adapter
├── state/                  # State management
├── service_context.py      # Service container
└── socketio_server.py      # Main server entry point
```

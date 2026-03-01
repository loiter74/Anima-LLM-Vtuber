# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

**Start everything**: `.\scripts\start.ps1` (Windows) or `./scripts/start.sh` (Unix)
**Stop everything**: `.\scripts\stop.ps1` (Windows) or `./scripts/stop.sh` (Unix)
**Backend only**: `python -m anima.socketio_server`
**Frontend only**: `cd frontend && pnpm dev`
**Default ports**: Backend `12394`, Frontend `3000`
**Config file**: `config/config.yaml`
**Environment**: `.env` for API keys (`GLM_API_KEY`, `LLM_API_KEY`, etc.)

## Architecture Decision Guide

**Quick navigation for common tasks**:

| Question | Solution |
|----------|----------|
| Need to modify emotion handling? | Use `UnifiedEventHandler` with plugin architecture |
| Need simple LLM tag emotions (`[happy]`)? | Use `UnifiedEventHandler` with `llm_tag_analyzer` |
| Need to add a new service provider? | See "Adding a New Service Provider" section |
| Need to debug WebSocket events? | See "Debugging Socket.IO Events" in Quick Workflows |
| Need to add custom emotion analyzer? | See "Adding a Custom Emotion Analyzer" in Quick Workflows |
| Need custom timeline strategy? | See "Adding a New Timeline Strategy" in Quick Workflows |
| Frontend can't connect? | See "Frontend Can't Connect to Backend" in Troubleshooting |
| Audio/Live2D not working? | Check `config/features/live2d.yaml` and see LIP_SYNC_IMPLEMENTATION.md |

## Additional Documentation

For more detailed information, refer to:
- **Documentation Index**: `docs/README.md` - Complete documentation index
- **Architecture**: `docs/architecture.md` - Complete system architecture (4+1 views documentation)
- **Frontend Architecture**: `docs/frontend/architecture.md` - Detailed frontend architecture overview
- **Component Guide**: `docs/frontend/component-guide.md` - Complete component usage reference
- **Feature Modules**: `docs/frontend/feature-modules.md` - Feature module patterns and best practices
- **API Reference**: `docs/frontend/api-reference.md` - Full API documentation for hooks, services, and types
- **Live2D Setup**: `docs/NEURO_SAMA_LIVE2D_SETUP.md` - Live2D model setup guide (Hiyori, Haru, Epsilon)
- **Lip Sync**: `docs/LIP_SYNC_IMPLEMENTATION.md` - Live2D lip sync feature testing and configuration guide

### Live2D Emotion System (NEW Architecture)
- **Refactoring Plan**: `docs/REFACTOR_PLAN.md` - Complete refactoring plan and design
- **Phase 1**: `docs/PHASE1_COMPLETE.md` - Interface definition and implementation
- **Phase 2**: `docs/PHASE2_COMPLETE.md` - Emotion analyzers enhancement
- **Phase 3**: `docs/PHASE3_COMPLETE.md` - Timeline strategies enhancement
- **Phase 4**: `docs/PHASE4_COMPLETE.md` - Unified event handler
- **Migration Guide**: `docs/REFACTOR_MIGRATION_GUIDE.md` - How to migrate to new architecture
- **Final Report**: `docs/REFACTOR_FINAL_REPORT.md` - Complete project summary

## Quick Workflows

### Adding a Custom Emotion Analyzer
```python
# 1. Create analyzer class in src/anima/live2d/analyzers/my_analyzer.py
from anima.live2d.analyzers.base import IEmotionAnalyzer, EmotionData

class MyCustomAnalyzer(IEmotionAnalyzer):
    def extract(self, text: str, context=None) -> EmotionData:
        # Your emotion extraction logic
        return EmotionData(emotions=[...], confidence=0.8)

    @property
    def name(self) -> str:
        return "my_analyzer"

# 2. Register in factory (or in __init__.py)
from anima.live2d.factory import EmotionAnalyzerFactory
EmotionAnalyzerFactory.register("my_analyzer", MyCustomAnalyzer)

# 3. Use in UnifiedEventHandler
handler = UnifiedEventHandler(
    websocket_send=ws.send,
    analyzer_type="my_analyzer"
)
```

### Adding a New Timeline Strategy
```python
# 1. Create strategy class in src/anima/live2d/strategies/my_strategy.py
from anima.live2d.strategies.base import ITimelineStrategy, TimelineSegment

class MyCustomStrategy(ITimelineStrategy):
    def calculate(self, emotions, text, audio_duration, **kwargs):
        # Your timeline calculation logic
        return [TimelineSegment(...)]

    @property
    def name(self) -> str:
        return "my_strategy"

# 2. Register in factory
from anima.live2d.factory import TimelineStrategyFactory
TimelineStrategyFactory.register("my_strategy", MyCustomStrategy)

# 3. Use in UnifiedEventHandler
handler = UnifiedEventHandler(
    websocket_send=ws.send,
    strategy_type="my_strategy"
)
```

### Debugging WebSocket Events
**Backend**:
```yaml
# .user_settings.yaml
log_level: DEBUG
```

**Frontend**:
```typescript
// In browser console
import { logger } from '@/shared/utils/logger'
logger.setLogLevel('DEBUG')
```

**Check event flow**:
- Backend: Add logging in handlers (`logger.debug(f"[{session_id}] Event: {event.type}")`)
- Frontend: Check SocketService.ts event handlers
- Use browser DevTools Network tab to inspect WebSocket frames

## Testing

### Running Tests
```bash
# Live2D Emotion System Tests (Phase 1-4)
python tests/test_phase1_interfaces.py      # Interface tests (5 tests)
python tests/test_phase2_analyzers.py       # Analyzer tests (13 tests)
python tests/test_phase3_strategies.py      # Strategy tests (16 tests)
python tests/test_phase4_unified_handler.py # Unified handler tests (10 tests)

# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src/anima/live2d --cov-report=html
```

**Test Coverage**: Phase 1-4 complete with 44 tests, 100% pass rate

### Usage Examples
See `examples/phase1_usage_examples.py` for Live2D emotion system usage examples.

## Common Development Commands

### Backend (Python)
```bash
# Start the Socket.IO server (main entry point)
python -m anima.socketio_server

# Start with custom config file
python -m anima.socketio_server path/to/config.yaml

# Install dependencies
pip install -r requirements.txt

# For Faster-Whisper ASR (optional, better audio format support)
pip install pydub
```

### Frontend (Next.js)
```bash
cd frontend
pnpm dev        # Start dev server
pnpm build      # Build for production
pnpm start      # Start production server
pnpm lint       # Run ESLint
```

**Testing**:
- See "Quick Workflows" → "Testing" section for backend test commands
- **Frontend**: Manual testing with browser dev tools + console logs
- **E2E**: Playwright available but not configured yet

### Live2D Model Setup
- `scripts/download_live2d.ps1` - Download Live2D Haru model (Windows PowerShell)
- `scripts/download_live2d_model.py` - Download Live2D Haru model (Python, cross-platform)

**Note**: The project supports multiple Live2D models:
- **Hiyori** (recommended) - Official free model, configured in `config/features/live2d.yaml`
- **Haru** - Alternative model
- **Epsilon** - Neuro-sama style model

See `docs/NEURO_SAMA_LIVE2D_SETUP.md` for detailed setup instructions.

**Quick setup (Windows PowerShell):**
```powershell
.\scripts\download_live2d.ps1
```

**Quick setup (Unix/macOS):**
```bash
python scripts/download_live2d_model.py
```

### Startup Scripts
- `scripts/start.sh` - Unix startup script (starts both backend and frontend)
- `scripts/start.bat` - Windows batch startup script
- `scripts/start.ps1` - PowerShell startup script (recommended on Windows)
- `scripts/stop.sh` - Unix stop script (Linux/macOS)
- `scripts/stop.bat` / `scripts/stop.ps1` - Windows stop scripts

All scripts support options:
- `--skip-backend` / `--skip-frontend` - Start/stop only one service
- `--install` - Reinstall dependencies before starting (start scripts only)
- `--help` - Show help information

**PowerShell Note**: PowerShell scripts use PascalCase parameters:
- `-SkipBackend` (not `--skip-backend`)
- `-SkipFrontend` (not `--skip-frontend`)
- `-Install` (not `--install`)
- `-Help` (not `--help`)

**Quick start (Windows PowerShell):**
```powershell
.\scripts\start.ps1
# Or with dependency reinstall
.\scripts\start.ps1 -Install
```

**Quick start (Unix/macOS):**
```bash
./scripts/start.sh
```

### Stop Services
```powershell
# Windows PowerShell
.\scripts\stop.ps1

# Unix/macOS
./scripts/stop.sh
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
- **Handler Registration**: Use `register_handler(event_type, handler)` to add handlers to the EventBus
  ```python
  orchestrator.register_handler("sentence", text_handler)
  orchestrator.register_handler("audio", audio_handler)
  ```
- **Priority Registration**: Pass `priority=EventPriority.HIGH` to control handler execution order

**1.1 SessionManager (`src/anima/services/conversation/session_manager.py`)**
- Factory-based session manager alternative to direct dict storage
- Methods: `set_factory(factory_func)`, `get_or_create(session_id)`, `cleanup(session_id)`
- Use when you need centralized session lifecycle management
- Currently socketio_server.py uses simple dict (`session_contexts` and `orchestrators`)

**2. ServiceContext (`src/anima/service_context.py`)**
- Service container holding ASR, TTS, LLM, and VAD engine instances
- VAD (Voice Activity Detection) options: `silero` (Silero VAD model), `mock`
- **VAD System**: Automatically detects speech in audio stream, triggers ASR when silence detected
  - Silero VAD: Uses pre-trained torch model for voice activity detection
  - Mock VAD: Always returns true (useful for testing)
  - **Audio Requirements**: Expects 16kHz sample rate, configurable via `config/services/vad/silero.yaml`
  - **VAD Timeout**: 15-second safety timeout prevents hanging if speech end isn't detected
  - **Tunable Parameters**: `prob_threshold`, `db_threshold`, `required_hits`, `required_misses`, `smoothing_window`
- Lazy initialization - services loaded via `load_from_config(AppConfig)`
- Services use factory pattern: `AgentFactory.create_from_config()`
- Lifecycle management: `async def close()` cleans up all resources

**3. Pipeline System (`src/anima/pipeline/`)**
- Chain-of-responsibility pattern for data processing

**InputPipeline** (`input_pipeline.py`):
- Processes user input before Agent
- Default steps: `ASRStep` (audio→text) → `TextCleanStep`
- Each step receives and modifies `PipelineContext`

**EmotionExtractionStep** (`steps/emotion_extraction_step.py`):
- Extracts emotion tags from LLM response (format: `[emotion]` like `[happy]`, `[sad]`)
- Cleans text by removing tags before TTS processing
- Stores extracted emotions in `metadata["emotions"]` as `EmotionTag` objects (with emotion name and position)
- Stores `metadata["has_emotions"]` boolean flag
- Configurable via `config/prompts/live2d_expression.txt`
- Validates extracted emotions against `valid_emotions` list from `Live2DConfig`
- Example: `"Hello [happy] world!"` → cleaned: `"Hello  world!"`, emotions: `[EmotionTag("happy", 6)]`

**OutputPipeline** (`output_pipeline.py`):
- Processes Agent streaming response
- Iterates through `chat_stream()` AsyncIterator
- Emits `OutputEvent`s to EventBus for each chunk
- Sends completion marker (empty text event) when streaming finishes
- Handles interruption via `interrupt()` method
- **Integration with Live2D**: When Live2D is enabled, coordinates with `EmotionExtractionStep` and `AudioExpressionHandler` to send unified `audio_with_expression` events containing audio, volume envelope, and emotion timeline

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
- **Priority Levels**: Use `EventPriority.HIGH`, `EventPriority.NORMAL`, `EventPriority.LOW` to control handler execution order

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
- `ExpressionHandler` - Handles Live2D character expression events
  - Maps conversation states to Live2D expressions (idle, listening, thinking, speaking, surprised, sad)
  - Sends `expression` events via WebSocket to frontend
  - Located at: `src/anima/handlers/expression_handler.py`
- `AudioExpressionHandler` - Legacy unified handler for audio + expression events
  - Processes `AUDIO_WITH_EXPRESSION` events
  - Combines audio data, volume envelope (for lip-sync), and emotion timeline into single WebSocket message
  - Calculates volume envelope at 50Hz sample rate
  - Calculates emotion timeline segments from emotion tags
  - Sends `audio_with_expression` event to frontend
  - Located at: `src/anima/handlers/audio_expression_handler.py`
- `UnifiedEventHandler` - **NEW**: Enhanced unified handler using plugin architecture
  - Supports pluggable emotion analyzers (`llm_tag_analyzer`, `keyword_analyzer`)
  - Supports pluggable timeline strategies (`position_based`, `duration_based`, `intensity_based`)
  - Factory-based component creation via `EmotionAnalyzerFactory` and `TimelineStrategyFactory`
  - Same event format as `AudioExpressionHandler` for frontend compatibility
  - Located at: `src/anima/handlers/unified_event_handler.py`
- `SocketEventAdapter` - Adapts backend events to frontend format
  - Maps event names: `sentence` → `text`, `user-transcript` → `transcript`
  - Adds missing fields for frontend compatibility
  - Can be disabled via `enable_adapter=False`

**Handler Selection Guide**:

| Use Case | Recommended Handler | Notes |
|----------|---------------------|-------|
| All use cases | `UnifiedEventHandler` | Plugin architecture with configurable analyzers/strategies |
| LLM tag emotions | `UnifiedEventHandler` + `llm_tag_analyzer` | Extracts `[happy]`, `[sad]` tags from LLM responses |
| Keyword-based emotions | `UnifiedEventHandler` + `keyword_analyzer` | No LLM tags required, 80+ keywords |
| Custom emotion analysis | `UnifiedEventHandler` + custom analyzer | Factory pattern for extensibility |
| Complex timeline strategies | `UnifiedEventHandler` + custom strategy | Duration/intensity-based allocation |

**Architecture (2026-03 Refactoring)**:

| Component Type | Implementation | Location |
|----------------|----------------|----------|
| Emotion Analysis | `StandaloneLLMTagAnalyzer`, `KeywordAnalyzer` | `src/anima/live2d/analyzers/` |
| Timeline Calculation | `PositionBasedStrategy`, `DurationBasedStrategy`, `IntensityBasedStrategy` | `src/anima/live2d/strategies/` |
| Event Handler | `UnifiedEventHandler` (uses plugins) | `src/anima/handlers/unified_event_handler.py` |
| Factory System | `EmotionAnalyzerFactory`, `TimelineStrategyFactory` | `src/anima/live2d/factory.py` |

**6. Provider Registry (`src/anima/config/core/registry.py`)**
- Decorator-based plugin system
- `@ProviderRegistry.register_config("llm", "openai")` - registers config class
- `@ProviderRegistry.register_service("llm", "openai")` - registers service class
- Supports discriminated unions for type-safe config loading

**7. Live2D Expression System**
- Frontend feature module at `frontend/features/live2d/`
- **Configuration Files** (two separate configs):
  - **Backend**: `config/features/live2d.yaml` - Model path, scale, position, emotion_map, lip_sync settings
  - **Frontend**: `frontend/public/config/live2d.json` - Live2D model settings and motion indices
- **Plugin Architecture** (2026-03 Refactoring Complete):
  - **Analyzers** (`src/anima/live2d/analyzers/`): Extract emotions from text
    - `StandaloneLLMTagAnalyzer` - Extracts `[happy]`, `[sad]` tags from LLM responses (independent implementation)
    - `KeywordAnalyzer` - Keyword-based matching (80+ keywords, 6 emotions)
    - Create custom analyzers via `IEmotionAnalyzer` interface
  - **Strategies** (`src/anima/live2d/strategies/`): Calculate emotion timelines
    - `position_based` - Position-based time allocation
    - `duration_based` - Duration-based allocation with weights
    - `intensity_based` - Intensity-based allocation with confidence
    - Create custom strategies via `ITimelineStrategy` interface
  - **Factory** (`src/anima/live2d/factory.py`): Dynamic component creation
    - `EmotionAnalyzerFactory.create(name, config)` - Create analyzers
    - `TimelineStrategyFactory.create(name, config)` - Create strategies
- **Handler**:
  - `UnifiedEventHandler` - Plugin-based handler with configurable analyzers/strategies
- **Utilities**:
  - `AudioAnalyzer` - Computes 50Hz volume envelope for lip-sync
  - `EmotionPromptBuilder` - Builds emotion prompt for LLM
- **Frontend Components**:
  - `Live2DService` - Model loading and expression control
  - `LipSyncEngine` - Basic lip-sync animation at ~30fps using EMA smoothing
  - `AdvancedLipSyncEngine` - **NEW**: Advanced lip-sync with Kalman filtering, adaptive thresholds, speech detection, and time compensation
  - `ExpressionTimeline` - Emotion timeline playback synchronized with audio
  - `useLive2D` hook - React hook for Live2D integration
- **Documentation**:
  - See "Quick Workflows" → "Adding a Custom Emotion Analyzer" for examples
  - See `docs/REFACTOR_MIGRATION_GUIDE.md` for migration from legacy to new architecture
  - See `docs/LIP_SYNC_IMPLEMENTATION.md` for lip sync troubleshooting

**audio_with_expression Event Structure**:
```json
{
  "type": "audio_with_expression",
  "audio_data": "base64_encoded_audio",
  "format": "mp3",
  "volumes": [0.1, 0.2, ...],  // 50Hz volume envelope for lip-sync
  "expressions": {
    "segments": [
      {"emotion": "happy", "time": 0.0, "duration": 2.5},
      {"emotion": "neutral", "time": 2.5, "duration": 1.0}
    ],
    "total_duration": 3.5
  },
  "text": "cleaned response text",
  "seq": 1
}
```
- **Frontend Components**:
  - `Live2DService` - Manages Live2D model loading and expression control
    - Uses `pixi-live2d-display` library for rendering
    - Dynamic library imports to avoid SSR issues
    - Canvas resize handling and window resize listeners
  - `LipSyncEngine` - Handles lip-sync animation during audio playback
    - Updates mouth parameter at ~30fps using `requestAnimationFrame`
    - Applies exponential moving average (EMA) for smooth transitions
    - Configurable sensitivity and smoothing
  - `ExpressionTimeline` - TypeScript class that plays emotion timeline segments synchronized with audio playback using `requestAnimationFrame`
  - `useLive2D` hook - React hook for Live2D integration
  - `Live2DViewer` component - Renders Live2D model in canvas
- **Event Flow**:
  - Emotion-based: LLM response → `EmotionExtractionStep` → emotion tags (`[happy]`, etc.) → `UnifiedEventHandler` → `audio_with_expression` event → Frontend
  - State-based: Backend emits `expression` event → Frontend `useConversation` receives → `Live2DViewer` updates model
- **audio_with_expression Event Structure**:
  ```json
  {
    "type": "audio_with_expression",
    "audio_data": "base64_encoded_audio",
    "format": "mp3",
    "volumes": [0.1, 0.2, ...],  // 50Hz volume envelope for lip-sync
    "expressions": {
      "segments": [
        {"emotion": "happy", "time": 0.0, "duration": 2.5},
        {"emotion": "neutral", "time": 2.5, "duration": 1.0}
      ],
      "total_duration": 3.5
    },
    "text": "cleaned response text",
    "seq": 1
  }
  ```
- **Library**: Uses `pixi-live2d-display` for Live2D model rendering
- **Model Configuration**:
  - Backend: `config/features/live2d.yaml` - Controls emotion-based expression mapping from LLM responses
  - Frontend: `frontend/public/config/live2d.json` - Controls Live2D model motion indices for state-based expressions
- **Emotion Mapping**: Maps emotion names to Live2D motion indices (e.g., `happy: 3`, `sad: 1`)

**Lip Sync Configuration** (`config/features/live2d.yaml` → `lip_sync`):
- `enabled` (boolean) - Whether lip sync is enabled
- `sensitivity` (float, default: 1.0) - Mouth opening sensitivity (0.5 - 2.0)
- `smoothing` (float, default: 0.5) - Smoothing factor for mouth animation (0.0 - 1.0)
- `min_threshold` (float, default: 0.05) - Minimum volume threshold to filter background noise
- `max_value` (float, default: 1.0) - Maximum mouth opening value
- `use_mouth_form` (boolean, default: false) - Whether to control mouth shape parameter

**Advanced Lip Sync Configuration** (`AdvancedLipSyncEngine`):
- `updateInterval` (number, default: 33) - Update frequency limit in ms (~30fps)
- `enableSmoothing` (boolean, default: true) - Enable Kalman filter smoothing
- `smoothingFactor` (number, default: 0.3) - Kalman filter smoothing coefficient
- `baseVolumeMultiplier` (number, default: 2.0) - Base volume multiplier
- `minThreshold` (number, default: 0.02) - Minimum volume threshold
- `timeCompensationFrames` (number, default: 2) - Time compensation in frames (~66ms @ 30fps)
- `curveIntensity` (number, default: 0.6) - Non-linear curve strength (0=linear, 1=fully non-linear)
- `enableAdaptiveThreshold` (boolean, default: true) - Enable adaptive threshold
- `adaptiveWindow` (number, default: 50) - Adaptive threshold window size
- `speechDetectionWindow` (number, default: 15) - Speech detection window in frames (~500ms @ 30fps)
- `speechThreshold` (number, default: 0.03) - Speech detection threshold
- `pauseDetectionWindow` (number, default: 30) - Pause detection window in frames (~1s @ 30fps)
- `pauseCloseSpeed` (number, default: 0.1) - Mouth closing speed during pause

**Lip Sync Engine Selection**:
- **Basic**: `LipSyncEngine` - Simple EMA-based smoothing, suitable for most cases
- **Advanced**: `AdvancedLipSyncEngine` - Kalman filtering + speech detection, for production use

For troubleshooting lip sync issues, see `docs/LIP_SYNC_IMPLEMENTATION.md`.

## Configuration System

### Supported Services

| Type | Providers |
|------|-----------|
| LLM | OpenAI, GLM (智谱 AI), Ollama, Mock |
| ASR | OpenAI Whisper, GLM ASR, Faster-Whisper, Mock |
| TTS | OpenAI TTS, GLM TTS, Edge TTS, Mock |
| VAD | Silero VAD, Mock |

**Default Service Configuration**:
- Edge TTS is the default TTS provider because it's free and has no quota limits (Microsoft)
- Silero VAD is the default VAD for production (mock available for testing)
- Faster-Whisper is the default ASR provider (free, offline, open-source)

**GLM (智谱 AI) Integration:**
- The project heavily uses GLM services for LLM, ASR, and TTS
- Uses `zai-sdk` (PyPI package `zai-sdk>=0.2.2`) - imported as `from zai`
  - Provides `ZhipuAiClient` for GLM API access
  - Handles LLM, ASR, and TTS services for GLM
  - Integrated via environment variable `GLM_API_KEY`
- Configuration files: `config/services/llm/glm.yaml`, `config/services/asr/glm.yaml`, `config/services/tts/glm.yaml`
- **Environment Variable**: `GLM_API_KEY` (checked first) or `LLM_API_KEY` (fallback)
- API key loaded from `.env` file at project root or system environment variables

**Faster-Whisper ASR:**
- Open-source, offline speech recognition based on OpenAI Whisper
- Free and runs locally after model download
- Installation: `pip install faster-whisper` (optional: `pip install pydub` for better audio format support)
- Recommended model: `large-v3` for best Chinese accuracy, `distil-large-v3` for speed
- Configuration: `config/services/asr/faster_whisper.yaml`
- Requires no API key, models are downloaded automatically on first use (~1-3GB depending on model)
- GPU support: Set `device: cuda` and `compute_type: float16` in config for faster inference

**Edge TTS:**
- Microsoft's free TTS service with no quota limits
- No API key required
- Configuration: `config/services/tts/edge.yaml`
- Multiple voices available, defaults to Chinese female voice

**Silero VAD:**
- Pre-trained torch model for voice activity detection
- Automatically detects when user stops speaking
- Configuration: `config/services/vad/silero.yaml`
- 15-second safety timeout prevents hanging if speech end isn't detected

### Modular Service Configuration

Services are configured as separate YAML files under `config/services/`:

```
config/
├── config.yaml              # Main config
├── services/
│   ├── asr/
│   │   ├── openai.yaml
│   │   ├── glm.yaml
│   │   ├── faster_whisper.yaml
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
  asr: faster_whisper   # Loads config/services/asr/faster_whisper.yaml
  tts: edge             # Loads config/services/tts/edge.yaml (free, no quota)
  agent: glm
  vad: silero           # VAD for speech activity detection

persona: "neuro-vtuber"
```

### Persona System

Personas define the AI's character and system prompt:
- Located in `config/personas/`
- Referenced by `persona` field in config.yaml
- Built into system prompt via `app_config.get_system_prompt()`
- Fields: name, description, system_prompt, greeting, etc.

**Live2D Expression Prompts** (`config/prompts/live2d_expression.txt`):
- Instructions for LLM on how to use emotion tags in responses
- Defines available emotions: `[happy]`, `[sad]`, `[angry]`, `[surprised]`, `[neutral]`, `[thinking]`
- Emotion tags use bracket format: `[emotion]` (e.g., `[happy]`)
- Emotion tags are automatically stripped from text before TTS
- Example: `"Hello! [happy] Nice to meet you!"` → TTS receives "Hello!  Nice to meet you!"
- Includes usage guidelines: don't overuse, choose appropriate emotions for context
- Built into system prompt via `EmotionPromptBuilder` in Live2D module

### User Settings System

User-specific settings are managed separately from project configuration:
- `UserSettings` class (`src/anima/config/user_settings.py`)
- Persisted to `.user_settings.yaml` in project root (excluded from git)
- Primary use: Runtime log level configuration
- Loaded automatically at server startup
- Methods: `get_log_level()`, `set_log_level(level)`, `save()`

### Feature Configuration

Features are configured as separate YAML files under `config/features/`:

**Live2D Configuration** (`config/features/live2d.yaml`):
```yaml
enabled: true
model:
  path: "/live2d/haru/haru_greeter_t03.model3.json"
  scale: 0.5
  position:
    x: 0
    y: 0
expressions:
  idle: "idle"
  listening: "listening"
  thinking: "thinking"
  speaking: "speaking"
  surprised: "surprised"
  sad: "sad"
lip_sync:
  enabled: true
  sensitivity: 1.0
  smoothing: 0.5
```

### Adding New UI Components

The project uses **shadcn/ui** for UI components. To add new components:

```bash
cd frontend
pnpm dlx shadcn@latest add [component-name]
```

Components are added to `frontend/components/ui/` and follow the shadcn/ui pattern:
- Use Radix UI primitives for accessibility
- Style with Tailwind CSS
- Import utility `cn()` from `@/shared/utils/cn` for className merging

**Example usage**:
```tsx
import { Button } from '@/components/ui/button'
import { cn } from '@/shared/utils/cn'

<Button className={cn('base-styles', className)} />
```

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

## Common Development Patterns

### Adding a New Event Type

1. **Add event type to enum** (`src/anima/core/events.py`):
   ```python
   class EventType(str, Enum):
       MY_NEW_EVENT = "my_new_event"
   ```

2. **Create handler** (`src/anima/handlers/my_handler.py`):
   ```python
   from anima.handlers.base_handler import BaseHandler

   class MyHandler(BaseHandler):
       async def handle(self, event: OutputEvent):
           # Handle the event
           await self.send({"type": "my_response", "data": event.data})
   ```

3. **Register in orchestrator** (`socketio_server.py` or `ConversationOrchestrator._setup_handlers`):
   ```python
   orchestrator.register_handler("my_new_event", my_handler, priority=EventPriority.NORMAL)
   ```

### Adding a New Pipeline Step

1. **Create step class** (`src/anima/pipeline/steps/my_step.py`):
   ```python
   from anima.pipeline.base import PipelineStep
   from anima.core.context import PipelineContext

   class MyStep(PipelineStep):
       async def process(self, ctx: PipelineContext) -> None:
           # Process the context
           ctx.text = ctx.text.upper()
           # Use ctx.skip_remaining = True to abort pipeline
   ```

2. **Add to pipeline** (`ConversationOrchestrator._setup_pipelines`):
   ```python
   # For InputPipeline
   self.input_pipeline.add_step(MyStep())

   # For OutputPipeline
   self.output_pipeline.add_step(MyStep())
   ```

### Adding a New Frontend Hook

1. **Create hook** (`frontend/features/myfeature/hooks/useMyFeature.ts`):
   ```typescript
   import { useMyFeatureStore } from '@/shared/state/stores/myFeatureStore'

   export function useMyFeature() {
     const state = useMyFeatureStore()
     return {
       // Expose state and actions
       ...state,
     }
   }
   ```

2. **Use in component**:
   ```typescript
   import { useMyFeature } from '@/features/myfeature/hooks/useMyFeature'

   function MyComponent() {
     const { data, action } = useMyFeature()
     // ...
   }
   ```

### Debugging Socket.IO Events

**Backend**: Add logging in handlers
```python
logger.debug(f"[{session_id}] Received event: {event.type}, data: {event.data}")
```

**Frontend**: Use browser console
```typescript
// In SocketService.ts
console.log('[Socket] Event received:', event, data)
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
- `EventType.AUDIO_WITH_EXPRESSION` - Combined audio + expression event (Live2D unified event)
- `EventType.EXPRESSION` - Live2D character expression (idle, listening, thinking, speaking, surprised, sad)
- `EventType.TOOL_CALL` - Function calling
- `EventType.CONTROL` - Control signals
- `EventType.ERROR` - Errors

**Completion Marker**:
- OutputPipeline sends empty text event when streaming finishes
- Includes `metadata: {"is_complete": true}` and incrementing `seq` number
- Frontend uses `lastProcessedSeq` to deduplicate completion markers
- Format: `{"type": "sentence" / "text", "text": "", "seq": N, "is_complete": true}`

## Socket.IO Events

### Event Flow Summary

```
Text Input Flow:
Client → text_input → InputPipeline (ASR → TextClean) → Agent.chat_stream()
→ OutputPipeline → EventBus → Handlers → WebSocket → Client

Audio Input Flow (VAD):
Client → raw_audio_data → VAD (detect speech end) → mic_audio_end
→ ASR → Agent → OutputPipeline → EventBus → Handlers → WebSocket → Client
```

### Event Mapping (SocketEventAdapter)

The `SocketEventAdapter` maps backend event names to frontend-expected names:
- `sentence` → `text`
- `user-transcript` → `transcript`
- Other events remain unchanged

Located at: `src/anima/handlers/socket_adapter.py`

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
- `audio_with_expression` - Unified audio + expression event for Live2D (contains audio_data, volumes, expressions timeline, text)
- `user-transcript` - ASR result
- `expression` - Live2D expression event (idle, listening, thinking, speaking, surprised, sad)
- `control` - Control signals (start-mic, stop-mic, interrupt, etc.)
- `error`

**Server → Client (after SocketEventAdapter)**:
- `text` - Adapted from `sentence` (frontend expects this)
- `transcript` - Adapted from `user-transcript`
- Other events remain unchanged

**Event Adapter Note**: `SocketEventAdapter` maps backend event names to frontend-expected names. Can be disabled by setting `enable_adapter=False` when registering handlers.

## Frontend Architecture Best Practices

**Component Pattern**:
```tsx
// ✅ Correct: Use hooks directly in components
function ChatPanel() {
  const { isConnected, messages, sendText } = useConversation()
  // ...
}

// ❌ Avoid: Don't create unnecessary Context wrappers
// The architecture uses hooks directly, no Context provider needed
```

**State Access Pattern**:
```tsx
// Option 1: Use useConversation hook (recommended for components)
import { useConversation } from '@/features/conversation/hooks/useConversation'

// Option 2: Use Zustand store directly (for fine-grained subscriptions)
import { useConversationStore } from '@/shared/state/stores/conversationStore'

// Only subscribe to specific state to avoid re-renders
const messages = useConversationStore(state => state.messages)
```

**Type Usage**:
```tsx
// Use shared types for basic data structures
import type { Message, ConversationStatus } from '@/shared/types'

// Store types are inferred automatically
import { useConversationStore } from '@/shared/state/stores/conversationStore'
type Store = ReturnType<typeof useConversationStore.getState>
```

## Troubleshooting

**Port Already in Use**:
- Backend (12394) or frontend (3000) port conflicts
- Use stop scripts: `.\scripts\stop.ps1` (Windows) or `./scripts/stop.sh` (Unix)
- Scripts verify port release and clean up temporary files

**GLM API Key Not Working**:
- Check `.env` file exists in project root
- Verify `GLM_API_KEY` is set (takes precedence over `LLM_API_KEY`)
- Server logs confirm `.env` loading on startup
- Fallback: GLM services degrade to Mock if API key missing

**VAD Issues**:
- Audio must be 16kHz sample rate
- Current default thresholds are set high to avoid false triggers from noise:
  - `prob_threshold: 0.8` - Only detects clear speech
  - `db_threshold: 40` - Filters out background noise
  - `required_hits: 8` - Requires ~0.24s of continuous speech to start
  - `required_misses: 20` - Requires ~0.65s of silence to stop
- Adjust sensitivity in `config/services/vad/silero.yaml`:
  - Lower `prob_threshold` (e.g., 0.5) for more sensitive detection
  - Lower `db_threshold` (e.g., 25-30) for quieter environments
  - Increase `required_misses` (e.g., 30-40) for longer speech pause tolerance
  - Decrease `required_hits` (e.g., 4) for faster speech start detection

**Frontend Can't Connect to Backend**:
- Verify backend is running on http://localhost:12394
- Check CORS settings in `socketio_server.py`
- Ensure frontend URL matches allowed origins

**Audio Interrupt Issues**:
- If audio doesn't stop when interrupted, check browser console for `AudioPlayer` logs
- The interrupt system relies on window references to track playing audio
- Common issue: `onplay` event delay may cause `isPlaying` flag to be out of sync
- Verify `window[AudioPlayer.WINDOW_AUDIO_KEY]` is set when audio plays

**Silero VAD Model Download Fails**:
- First run downloads model automatically (~66MB)
- Check internet connection if model fails to load
- Model cached locally after first download

**Faster-Whisper ASR Issues**:
- First run downloads model automatically (size varies: tiny ~40MB, distil-large-v3 ~1.5GB)
- If `faster-whisper` is not installed: `pip install faster-whisper`
- For better audio format support (MP3, etc.): `pip install pydub` (optional, fallback to wave module)
- Model files cached in `~/.cache/huggingface/` (or `download_root` if specified)
- For GPU acceleration: set `device: cuda` in config and install CUDA
- For faster CPU inference: set `compute_type: int8` in config

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

**Audio Buffering**:
- `AudioBufferManager` class manages audio chunks per session before processing
- Audio buffers stored in `audio_buffers: Dict[str, list]` keyed by session_id
- Used when client sends `mic_audio_data` before `mic_audio_end`

**Audio Processing**:
- Audio format: Float32 array, normalized to [-1.0, 1.0]
- Sample rate: 16kHz (required by VAD and ASR)
- Frontend AudioRecorder applies gain control (default: 50.0)
- **AudioPlayer Global Stop**:
  - `AudioPlayer.stopGlobalAudio()` stops all playing audio instances
  - Uses `window[AudioPlayer.WINDOW_AUDIO_KEY]` to track playing audio globally
  - Critical for interrupt system when new audio arrives
- **Audio Interrupt System**:
  - When new audio arrives while audio is playing, the system automatically stops old audio
  - `AudioInteractionService` manages interrupt logic by checking `AudioPlayer.isPlaying` before playback
  - Stop process: `audio.pause()` → `audio.src = ''` → `audio.load()` → clear window reference
  - Implemented via commit d895ab2 (2025-02-26)

**Lip Sync Engine Selection**:
- **Basic**: `LipSyncEngine` - Simple EMA-based smoothing, suitable for most use cases
- **Advanced**: `AdvancedLipSyncEngine` (NEW, 2026-02) - Production-ready with:
  - Kalman filtering for predictive smoothing
  - Adaptive threshold based on audio characteristics
  - Speech state detection (speaking/pause/silence)
  - Time compensation for audio-to-animation delay
  - Non-linear volume mapping for better sensitivity

**Auto-Interruption**:
- When VAD detects new speech start, it automatically interrupts ongoing responses
- Frontend interrupts audio playback when starting new recording
- Client sends `interrupt_signal` when user clicks interrupt button
- `ConversationOrchestrator.interrupt()` sets flag that pipelines check

**Async/Await**:
- Entire backend is async - use `await` for all I/O
- LLM and TTS return AsyncIterators for streaming

**Interrupt Handling**:
- `ConversationOrchestrator.interrupt()` sets `_interrupted` flag
- Both InputPipeline and OutputPipeline check this flag
- OutputPipeline breaks its async-for loop when interrupted

**Frontend Architecture**:
- **No Context Providers**: Components use hooks directly (simpler data flow)
- **State Management**: Zustand stores with persist middleware for conversation history
- **Type Inference**: Store types inferred from implementation, not duplicated
- **Hook Pattern**: `useConversation` provides all conversation functionality
- **Component Usage**:
  ```tsx
  // ✅ Correct: Use hook directly in component
  function ChatPanel() {
    const { isConnected, messages, sendText } = useConversation()
    // ...
  }
  ```
- **Direct Store Access** (for fine-grained subscriptions):
  ```tsx
  import { useConversationStore } from '@/shared/state/stores/conversationStore'
  const messages = useConversationStore(state => state.messages)
  ```

**Frontend Logging**:
- Uses custom `logger` from `@/shared/utils/logger`
- Supports log levels: DEBUG, INFO, WARN, ERROR, SILENT
- AudioPlayer has cleaned logs (25 essential logs vs 49 before)
- Check browser console for audio playback errors

**Environment Variables**:
- Use `${VAR_NAME}` in YAML configs for API keys
- Supported vars: `LLM_API_KEY`, `ASR_API_KEY`, `TTS_API_KEY`, etc.
- Environment variables can override config values:
  - `GLM_API_KEY` - GLM (智谱 AI) API key for LLM/ASR/TTS services (also checked as `LLM_API_KEY` fallback)
  - `LLM_API_KEY` - Generic LLM API key (used by GLM if `GLM_API_KEY` not set)
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
- Server logs confirm whether `.env` was loaded successfully

**Server Configuration**:
- Default port: `12394` (configurable in `config/config.yaml` under `system.port`)
- Default host: `localhost` (configurable under `system.host`)
- CORS allowed origins: `http://localhost:3000`, `http://127.0.0.1:3000`, `*`
- Custom config file: `python -m anima.socketio_server path/to/config.yaml`

**User Settings**:
- `UserSettings` class manages per-user configuration (not committed to git)
- Settings persisted to `.user_settings.yaml` in project root (excluded via .gitignore)
- Primary use: Log level persistence across server restarts
- Loaded at server startup via `user_settings = UserSettings(root_dir)`
- Methods: `get_log_level()`, `set_log_level(level)`, `save()`

**Logger Management**:
- `LoggerManager` (`src/anima/utils/logger_manager.py`) wraps loguru for dynamic log level switching
- Singleton instance: `logger_manager = LoggerManager.get_instance()`
- Use `logger_manager.set_level("DEBUG")` to change log level at runtime
- Valid levels: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL

**Graceful Shutdown**:
- Server handles SIGINT (Ctrl+C) and SIGTERM signals
- `cleanup_all_resources()` stops all orchestrators and closes service contexts
- Cross-platform signal handling (Windows/Unix)
- FastAPI lifespan manager ensures proper cleanup on server shutdown

## Frontend Structure

The frontend follows a **feature-based architecture** with clear separation of concerns:

### Data Flow Pattern

```
Component → useConversation Hook → Zustand Stores
```

**Key Design Principle**: No Context wrapper layer - components directly use hooks for state management

### Feature Modules (`frontend/features/`)

**Audio** (`features/audio/`):
- `services/AudioRecorder.ts` - Handles microphone recording with configurable gain control
- `services/AudioPlayer.ts` - Manages audio playback with global stop capability (stops all playing audio)
- `services/VADProcessor.ts` - Client-side Voice Activity Detection (optional)
- `hooks/useAudioRecorder.ts` - Hook for audio recording functionality
- `hooks/useAudioPlayer.ts` - Hook for audio playback with callbacks

**Connection** (`features/connection/`):
- `services/SocketClient.ts` - Low-level Socket.IO wrapper
- `services/SocketService.ts` - High-level service with event handler management
- `hooks/useSocket.ts` - Hook for Socket.IO connection management

**Conversation** (`features/conversation/`):
- `hooks/useConversation.ts` - Core conversation orchestrator (~400 lines)
  - Manages Socket.IO events: `text`, `audio`, `transcript`, `control`, `error`, `expression`
  - Coordinates AudioRecorder and AudioPlayer
  - Handles conversation state and message history
  - Auto-interrupts on new input
  - **No Context wrapper** - components call this hook directly

**Live2D** (`features/live2d/`):
- `services/Live2DService.ts` - Manages Live2D model loading, expression control, and lifecycle
- `services/LipSyncEngine.ts` - Basic lip-sync animation using exponential moving average (EMA) smoothing
- `services/AdvancedLipSyncEngine.ts` - Advanced lip-sync with:
  - **Time Compensation**: Audio-to-mouth animation delay compensation (~66ms)
  - **Non-linear Volume Mapping**: Logarithmic curve for better sensitivity
  - **Adaptive Threshold**: Dynamically adjusts silence threshold based on audio
  - **Kalman Filtering**: Predictive smoothing for natural mouth movement
  - **Speech State Detection**: Distinguishes between speaking, pause, and silence
  - **Pause Detection**: Gradual mouth closure during speech pauses (~1 second window)
- `services/ExpressionTimeline.ts` - Plays emotion timeline segments synchronized with audio playback using `requestAnimationFrame`
- `hooks/useLive2D.ts` - React hook for Live2D integration
- `types/index.ts` - TypeScript types for Live2D configuration (Live2DConfig, EmotionMap, etc.)
- Components: `Live2DViewer` (`components/vtuber/live2d-viewer.tsx`)

### State Management (`frontend/shared/state/stores/`)

Uses **Zustand** for global state:
- `audioStore.ts` - Recording/playback state, volume levels, errors
- `connectionStore.ts` - Socket connection status and session ID
- `conversationStore.ts` - Messages, current response, typing status
  - Tracks `lastProcessedSeq` to deduplicate completion markers
  - Uses persist middleware to save messages to localStorage

**Type Inference**: Store types are inferred from the store itself, not duplicated in separate type files

### Component Structure

- `app/` - Next.js App Router (`page.tsx` is the main entry point)
- `components/vtuber/` - VTuber-specific components
  - `chat-panel.tsx` - Main chat UI
  - `live-preview.tsx` - Live2D/live video preview
  - `live2d-viewer.tsx` - Live2D model viewer with expression sync
  - `bottom-toolbar.tsx` - Control toolbar
- `components/ui/` - shadcn/ui components (Radix UI + Tailwind)
- `shared/constants/events.ts` - Centralized Socket.IO event definitions
- `shared/constants/live2d.ts` - Live2D expression constants
- `shared/types/` - TypeScript type definitions (only shared types like `Message`, `ConversationStatus`, Live2D types)

**Frontend Development Notes:**
- Uses pnpm as package manager
- Next.js 16 with App Router
- React 19 with TypeScript
- Socket.IO for real-time communication
- shadcn/ui for component library (Radix UI primitives + Tailwind CSS)
- **No Context providers** - components use hooks directly for simpler data flow
- **Architecture Simplification (2025-02)**: Removed redundant Context layer, components now use hooks directly (`Component → Hook → Store` instead of 3-layer)

## Key Source Directories

```
src/anima/
├── config/                  # Configuration system
│   ├── core/               # Registry, base config classes
│   ├── providers/          # Provider configs (llm/, asr/, tts/, vad/)
│   ├── agent.py            # Agent configuration
│   ├── app.py              # Main AppConfig class
│   ├── persona.py          # Persona configuration
│   ├── live2d.py           # Live2D configuration (Live2DConfig, emotion_map, lip_sync)
│   ├── system.py           # System settings
│   └── user_settings.py    # User-specific settings (persisted to .user_settings.yaml)
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
│   └── steps/              # Pipeline steps (ASRStep, TextCleanStep, EmotionExtractionStep, etc.)
├── services/               # Service implementations
│   ├── llm/                # LLM/Agent services
│   ├── asr/                # ASR services (faster_whisper, glm, openai, mock)
│   ├── tts/                # TTS services
│   ├── vad/                # VAD services (silero, mock)
│   └── conversation/       # ConversationOrchestrator, SessionManager
├── handlers/               # Event handlers
│   ├── base_handler.py     # Base handler class
│   ├── text_handler.py     # Text output handler
│   ├── audio_handler.py    # Audio output handler
│   ├── expression_handler.py  # Live2D expression handler (state-based)
│   ├── audio_expression_handler.py  # Legacy unified audio + expression handler
│   ├── unified_event_handler.py    # NEW: Enhanced handler using plugin architecture
│   └── socket_adapter.py   # Socket event adapter
├── live2d/                 # Live2D expression system module
│   ├── analyzers/               # Emotion analyzer plugins
│   │   ├── base.py             # IEmotionAnalyzer interface
│   │   ├── llm_tag_analyzer.py # LLM tag extraction (supports [happy] tags)
│   │   └── keyword_analyzer.py # Keyword-based emotion matching
│   ├── strategies/              # Timeline calculation strategies
│   │   ├── base.py             # ITimelineStrategy interface
│   │   ├── position_based.py   # Position-based time allocation
│   │   ├── duration_based.py   # Duration-based allocation with weights
│   │   └── intensity_based.py  # Intensity-based allocation
│   ├── factory.py               # Factory classes for component creation
│   ├── emotion_extractor.py     # Legacy: Extracts [emotion] tags from text
│   ├── emotion_timeline.py      # Legacy: Calculates emotion timeline segments
│   ├── audio_analyzer.py        # Computes volume envelope for lip-sync
│   └── prompt_builder.py        # Builds emotion prompt for LLM
├── state/                  # State management
├── utils/                  # Utility modules
│   ├── logger_manager.py   # Dynamic log level management
│   └── __init__.py
├── service_context.py      # Service container
└── socketio_server.py      # Main server entry point
```

**Frontend**:
```
frontend/
├── public/
│   ├── config/
│   │   └── live2d.json     # Live2D model configuration
│   └── live2d/             # Live2D model files (downloaded separately)
├── features/
│   ├── audio/              # Audio recording, playback, VAD
│   ├── connection/         # Socket.IO connection management
│   ├── conversation/       # Chat state and message processing
│   └── live2d/             # Live2D model integration
│       ├── services/       # Live2DService, LipSyncEngine, ExpressionTimeline
│       ├── hooks/          # useLive2D hook
│       └── types/          # Live2D TypeScript types
├── components/
│   ├── ui/                 # shadcn/ui components
│   ├── vtuber/             # VTuber-specific components
│   └── layout/             # Layout components
├── shared/
│   ├── constants/          # Event definitions, Live2D constants
│   ├── state/stores/       # Zustand stores
│   ├── types/              # Shared TypeScript types (Message, ConversationStatus, Live2D types)
│   └── utils/              # Utility functions
└── app/                    # Next.js App Router
```
```

## Frontend Refactoring History

### 2025-02: Architecture Simplification

**Goal**: Reduce code complexity and improve learnability for frontend newcomers

**Changes**:
1. **Removed Context Redundancy** (-51 lines)
   - Deleted `contexts/conversation-context.tsx`
   - Components now use `useConversation` hook directly
   - Eliminated unnecessary abstraction layer

2. **Cleaned Debug Logs** (-80 lines)
   - Removed 24 CHECKPOINT debug logs from `AudioPlayer.ts`
   - Reduced log count from 49 to 25 (-49%)
   - Kept only essential error, warning, and status logs

3. **Simplified Type Definitions** (-14 lines)
   - Removed duplicate `ConversationState` and `ConversationActions` from `shared/types/conversation.ts`
   - Store types now inferred automatically from Zustand
   - Single source of truth for type definitions

**Impact**:
- Net code reduction: -145 lines
- Files changed: 8 (1 deleted, 7 modified)
- Architecture: `Component → Hook → Store` (simplified from 3-layer to 2-layer)
- Build status: ✅ All tests passing, TypeScript no errors

**Before**:
```
Component → ConversationContext → useConversation → Zustand Store
```

**After**:
```
Component → useConversation → Zustand Store
```

**Benefits**:
- ✅ Easier to understand for newcomers
- ✅ Less boilerplate code
- ✅ Clearer data flow
- ✅ Better TypeScript inference
- ✅ Cleaner console output

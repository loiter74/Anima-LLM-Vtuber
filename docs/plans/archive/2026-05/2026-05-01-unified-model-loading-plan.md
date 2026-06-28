# Unified Model Loading System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate inconsistent model loading delays by creating a centralized `ModelLoadingManager` with startup pre-warming.

**Architecture:** Introduce `ModelLoadingManager` as a singleton lifecycle coordinator. Each model service gets a `preload()` method and registers with the manager. At server startup, `warmup()` preloads all models concurrently in background. At session creation, `ServiceContext` uses `manager.get()` which returns immediately if already loaded, or awaits if still warming up. Socket.IO events provide frontend visibility.

**Tech Stack:** Python asyncio, asyncio.Event for await coordination, Socket.IO for progress events

**Design Doc:** `docs/plans/archive/2026-05/2026-05-01-unified-model-loading-design.md`

---

### Task 1: Create ModelLoadingManager class

**Files:**
- Create: `src/animetta/core/model_loading_manager.py`
- Test: `tests/core/test_model_loading_manager.py`

**Step 1: Write the test**

```python
import pytest
import asyncio
from anima.core.model_loading_manager import ModelLoadingManager, ModelLoadState

@pytest.mark.asyncio
async def test_register_and_get():
    manager = ModelLoadingManager()

    # Register a mock service
    async def loader():
        return "loaded_service"

    result = manager.register("test_svc", loader, "test_svc")
    assert result is not None

    # Should return immediately if already loaded by register
    svc = await manager.get("test_svc")
    assert svc == "loaded_service"

    # Status check
    status = manager.get_status()
    assert status["test_svc"] == "loaded"

@pytest.mark.asyncio
async def test_warmup_and_await():
    manager = ModelLoadingManager()

    async def slow_loader():
        await asyncio.sleep(0.1)
        return "slow_service"

    manager.register("slow", slow_loader, "slow")

    # Start warmup (non-blocking)
    warmup_task = asyncio.create_task(manager.warmup())

    # Get should await completion
    svc = await manager.get("slow")
    assert svc == "slow_service"

    await warmup_task

@pytest.mark.asyncio
async def test_get_status():
    manager = ModelLoadingManager()

    async def fast():
        return "ok"

    manager.register("a", fast, "a")
    status = manager.get_status()
    assert isinstance(status, dict)
    assert "a" in status

@pytest.mark.asyncio
async def test_warmup_concurrent():
    manager = ModelLoadingManager()
    order = []

    async def loader_a():
        await asyncio.sleep(0.05)
        order.append("a")
        return "A"

    async def loader_b():
        await asyncio.sleep(0.01)
        order.append("b")
        return "B"

    manager.register("a", loader_a, "a")
    manager.register("b", loader_b, "b")

    await manager.warmup()
    # b should finish before a (shorter sleep)
    assert order == ["b", "a"], f"Expected b before a, got {order}"

    assert await manager.get("a") == "A"
    assert await manager.get("b") == "B"

@pytest.mark.asyncio
async def test_load_error():
    manager = ModelLoadingManager()

    async def failing_loader():
        raise RuntimeError("Failed to load")

    manager.register("broken", failing_loader, "broken")

    with pytest.raises(RuntimeError):
        await manager.get("broken")

    status = manager.get_status()
    assert status["broken"] == "error"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_model_loading_manager.py -v`
Expected: FAIL with ModuleNotFoundError / ImportError

**Step 3: Write minimal implementation**

```python
"""
Model Loading Manager - centralized model lifecycle coordination

Provides:
- register services with async loader functions
- warmup() to preload all services concurrently
- get() to await a service's loading completion
- get_status() to check all loading states
"""

import asyncio
from enum import Enum
from typing import Any, Callable, Dict, Optional, Awaitable
from loguru import logger


class ModelLoadState(str, Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"


class ModelSlot:
    """Track a single model's loading lifecycle"""

    def __init__(self, name: str):
        self.name = name
        self.state = ModelLoadState.UNLOADED
        self.instance: Optional[Any] = None
        self.error: Optional[Exception] = None
        self._event = asyncio.Event()

    def set_loaded(self, instance: Any) -> None:
        self.instance = instance
        self.state = ModelLoadState.LOADED
        self._event.set()

    def set_error(self, error: Exception) -> None:
        self.error = error
        self.state = ModelLoadState.ERROR
        self._event.set()

    async def wait(self, timeout: float = 30.0) -> Any:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Model '{self.name}' did not load within {timeout}s")

        if self.error:
            raise self.error
        return self.instance


class ModelLoadingManager:
    """Centralized model loading lifecycle manager"""

    def __init__(self, socketio=None):
        self._slots: Dict[str, ModelSlot] = {}
        self._loader_fns: Dict[str, Callable[[], Awaitable[Any]]] = {}
        self._socketio = socketio

    def register(
        self,
        name: str,
        loader_fn: Callable[[], Awaitable[Any]],
        service_name: str,
    ) -> Any:
        """
        Register a service with an async loader function.

        If the loader_fn returns a result synchronously (already loaded),
        the slot is marked as loaded immediately.
        """
        slot = ModelSlot(name)
        self._slots[name] = slot
        self._loader_fns[name] = loader_fn

        # If service instance already returned (eager load), set immediately
        if asyncio.iscoroutinefunction(loader_fn):
            # Will be loaded during warmup or first get()
            slot.state = ModelLoadState.UNLOADED
        else:
            # Synchronous loader means already instantiated
            try:
                result = loader_fn()
                slot.set_loaded(result)
            except Exception as e:
                slot.set_error(e)

        return slot.instance

    async def warmup(self) -> None:
        """Start loading ALL registered services concurrently (non-blocking)"""
        tasks = []
        for name, loader_fn in self._loader_fns.items():
            slot = self._slots[name]
            if slot.state != ModelLoadState.UNLOADED:
                continue

            slot.state = ModelLoadState.LOADING
            tasks.append(self._load_one(name, loader_fn))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _load_one(self, name: str, loader_fn: Callable) -> None:
        """Load a single service"""
        slot = self._slots[name]
        try:
            logger.info(f"[ModelLoadingManager] Loading {name}...")
            self._emit_status(name, "loading", 0.0)

            instance = await loader_fn()

            slot.set_loaded(instance)
            logger.info(f"[ModelLoadingManager] {name} loaded successfully")
            self._emit_status(name, "loaded", 1.0)
        except Exception as e:
            slot.set_error(e)
            logger.error(f"[ModelLoadingManager] {name} failed to load: {e}")
            self._emit_status(name, "error", 0.0)

    async def get(self, name: str, timeout: float = 30.0) -> Any:
        """Get a loaded service instance (awaits if still loading)"""
        if name not in self._slots:
            raise KeyError(f"Model '{name}' not registered")

        slot = self._slots[name]

        # If still UNLOADED, start loading now (fallback)
        if slot.state == ModelLoadState.UNLOADED:
            slot.state = ModelLoadState.LOADING
            asyncio.create_task(self._load_one(name, self._loader_fns[name]))

        # If already loaded, return immediately
        if slot.state == ModelLoadState.LOADED:
            return slot.instance

        # Wait for loading
        return await slot.wait(timeout=timeout)

    def get_status(self) -> Dict[str, str]:
        """Get loading status of all registered services"""
        return {name: slot.state.value for name, slot in self._slots.items()}

    async def wait_all(self, timeout: float = 60.0) -> bool:
        """Wait until all registered models are loaded"""
        tasks = [slot.wait(timeout=timeout) for slot in self._slots.values()
                 if slot.state in (ModelLoadState.LOADING, ModelLoadState.UNLOADED)]
        if not tasks:
            return True
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(r is not None and not isinstance(r, Exception) for r in results)

    def _emit_status(self, name: str, status: str, progress: float) -> None:
        """Emit loading status via Socket.IO"""
        if not self._socketio:
            return
        try:
            import asyncio
            asyncio.create_task(self._socketio.emit("model_loading_status", {
                "name": name,
                "status": status,
                "progress": progress,
                "all_models": self.get_status(),
            }))
        except Exception:
            pass
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_model_loading_manager.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/core/test_model_loading_manager.py src/animetta/core/model_loading_manager.py
git commit -m "feat: add ModelLoadingManager for centralized model lifecycle"
```

---

### Task 2: Add preload() to FasterWhisperASR (idempotent)

**Files:**
- Modify: `src/animetta/services/speech/asr/faster_whisper_asr.py:116-130`

**Step 1: Write the failing test**

Add to `tests/services/test_faster_whisper_asr.py` (create if needed):

```python
import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_preload_idempotent():
    """preload() should be safe to call multiple times"""
    from anima.services.speech.asr.faster_whisper_asr import FasterWhisperASR

    asr = FasterWhisperASR(model="base", device="cpu")

    with patch.object(asr, '_get_model') as mock_get_model:
        mock_get_model.return_value = MagicMock()

        # First call should call _get_model
        await asr.preload()
        assert mock_get_model.call_count == 1

        # Second call should NOT call _get_model again
        await asr.preload()
        assert mock_get_model.call_count == 1  # Still 1
```

**Step 2: Implement the fix**

In `faster_whisper_asr.py`, modify `preload()`:

```python
async def preload(self) -> None:
    """Preload the model (idempotent - safe to call multiple times)"""
    if self._model is not None:
        logger.debug(f"Faster-Whisper model already loaded, skipping preload")
        return

    logger.info(f"Preloading Faster-Whisper model: {self.model_name}...")

    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, self._get_model)

    logger.info(f"Faster-Whisper model preloaded successfully")
```

**Step 3: Run test**

Run: `pytest tests/services/test_faster_whisper_asr.py::test_preload_idempotent -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/animetta/services/speech/asr/faster_whisper_asr.py
git commit -m "refactor: make FasterWhisperASR.preload() idempotent"
```

---

### Task 3: Add preload() to ChatTTSTTS

**Files:**
- Modify: `src/animetta/services/speech/tts/chattts_tts.py:58-93`

**Step 1: Write the test**

```python
@pytest.mark.asyncio
async def test_chattts_preload_idempotent():
    from anima.services.speech.tts.chattts_tts import ChatTTSTTS

    tts = ChatTTSTTS(model_path="/fake/path", device="cpu")

    with patch.object(tts, '_ensure_loaded') as mock_ensure:
        await tts.preload()
        assert mock_ensure.call_count == 1

        await tts.preload()
        assert mock_ensure.call_count == 1  # Once only
```

**Step 2: Add preload() method to ChatTTSTTS**

```python
async def preload(self) -> None:
    """Preload the ChatTTS model from disk to GPU (idempotent)"""
    if self._chat is not None:
        logger.debug(f"ChatTTS model already loaded, skipping preload")
        return

    logger.info(f"Preloading ChatTTS model from {self.model_path}...")

    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, self._ensure_loaded)

    logger.info(f"ChatTTS model preloaded successfully")
```

**Step 3: Run test**

Run: `pytest tests/services/test_chattts_tts.py::test_chattts_preload_idempotent -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/animetta/services/speech/tts/chattts_tts.py
git commit -m "feat: add preload() to ChatTTSTTS for eager loading support"
```

---

### Task 4: Add preload() to SileroVAD

**Files:**
- Modify: `src/animetta/services/intelligence/vad/silero_vad.py:48,77-90`

**Step 1: Write test**

```python
@pytest.mark.asyncio
async def test_silero_vad_preload():
    from anima.services.intelligence.vad.silero_vad import SileroVAD

    vad = SileroVAD()

    # Preload should be safe after construction (model already loaded)
    await vad.preload()
    assert vad.model is not None
```

**Step 2: Add preload() method to SileroVAD**

After `_load_vad_model()`, add:

```python
async def preload(self) -> None:
    """Preload is a no-op for SileroVAD (model loaded eagerly in __init__)"""
    if self.model is None:
        logger.info("Loading Silero-VAD model...")
        import asyncio
        loop = asyncio.get_event_loop()
        self.model = await loop.run_in_executor(None, self._load_vad_model)
        logger.info("Silero-VAD model loaded")
    else:
        logger.debug("Silero-VAD model already loaded, skipping preload")
```

**Step 3:** Run test

Run: `pytest tests/services/test_silero_vad.py::test_silero_vad_preload -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/animetta/services/intelligence/vad/silero_vad.py
git commit -m "feat: add preload() to SileroVAD for unified loading interface"
```

---

### Task 5: Add preload() to GLMLLM

**Files:**
- Modify: `src/animetta/services/intelligence/llm/glm_llm.py:36-39`

**Step 1: Write test**

```python
@pytest.mark.asyncio
async def test_glm_llm_preload():
    from anima.services.intelligence.llm.glm_llm import GLMLLM
    from unittest.mock import patch, MagicMock

    config = MagicMock()
    config.api_key = "test-key"
    config.model = "glm-4"
    config.temperature = 0.7
    config.max_tokens = 1024

    llm = GLMLLM(config=config)

    with patch('zhipuai.ZhipuAI') as mock_zhipu:
        mock_zhipu.return_value = MagicMock()

        await llm.preload()
        assert mock_zhipu.call_count == 1
        assert llm.client is not None

        # Second call should be no-op
        await llm.preload()
        assert mock_zhipu.call_count == 1  # Still 1
```

**Step 2: Add preload() method to GLMLLM**

```python
async def preload(self) -> None:
    """Preload the ZhipuAI API client (lightweight, idempotent)"""
    if self.client is not None:
        return
    await self._ensure_client()
    logger.info(f"[GLM] API client preloaded (model={self.config.model})")
```

**Step 3:** Run test

Run: `pytest tests/services/test_glm_llm.py::test_glm_llm_preload -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/animetta/services/intelligence/llm/glm_llm.py
git commit -m "feat: add preload() to GLMLLM for eager client init"
```

---

### Task 6: Integrate ModelLoadingManager into WebSocketServer lifecycle

**Files:**
- Modify: `src/animetta/orchestration/server/websocket.py`
- Modify: `src/animetta/core/socketio_server.py`

**Step 1: Write integration test**

```python
@pytest.mark.asyncio
async def test_server_model_manager():
    from anima.orchestration.server.websocket import WebSocketServer

    server = WebSocketServer(config=MagicMock())
    assert server.model_manager is not None
    assert server.model_manager.get_status() == {}

    # After setup, should have registered services
    await server.start()
    # Services should be registered (not necessarily loaded yet)
    assert len(server.model_manager.get_status()) > 0
```

**Step 2: Modify WebSocketServer**

In `websocket.py`:
- Add `self.model_manager = ModelLoadingManager(socketio=self.sio)` in `__init__`
- In `create_server()`, call `await server.model_manager.warmup()` after setup

```python
# In websocket.py WebSocketServer.__init__:
from anima.core.model_loading_manager import ModelLoadingManager

def __init__(self, config=None):
    # ... existing code ...
    self.session_manager = SessionManager()
    self.model_manager = ModelLoadingManager()  # Will set socketio later
    # ... rest of init ...

def set_socketio(self, sio):
    """Wire up Socket.IO for status events"""
    self.model_manager._socketio = sio
```

In `socketio_server.py` `create_server()`:
```python
def create_server(config=None) -> WebSocketServer:
    server = WebSocketServer(config)
    server.setup_routes()
    server.setup_lifecycle()
    # Wire Socket.IO to model manager
    server.model_manager._socketio = server.sio
    return server
```

**Step 3:** Run test

Run: `pytest tests/orchestration/test_server_model_manager.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/animetta/orchestration/server/websocket.py src/animetta/core/socketio_server.py
git commit -m "feat: integrate ModelLoadingManager into server lifecycle"
```

---

### Task 7: Modify ServiceContext to use ModelLoadingManager

**Files:**
- Modify: `src/animetta/core/service_context.py`

**Step 1: Identify loading points**

In `service_context.py`, the key change is:
- `load_from_config()` should NOT eagerly init services directly
- Instead, register services with the manager and await their loading
- Replace `_preload_asr_background()` with manager warmup

**Step 2: Modify ServiceContext to accept manager**

Add to `ServiceContext.__init__`:
```python
def __init__(self, model_manager: Optional[ModelLoadingManager] = None):
    # ... existing ...
    self.model_manager = model_manager
```

Modify `load_from_config()` to use manager:
```python
async def load_from_config(self, config: AppConfig) -> None:
    self.config = config
    logger.info(f"[{self.session_id}] Loading services from config...")

    # If we have a model manager, use it to coordinate loading
    if self.model_manager:
        # Register services with the manager for coordinated loading
        # Manager returns immediately if already loaded via warmup
        self.asr_engine = await self.model_manager.get("asr", timeout=60)
        self.tts_engine = await self.model_manager.get("tts", timeout=60)
        self.llm_engine = await self.model_manager.get("llm", timeout=60)
        self.vad_engine = await self.model_manager.get("vad", timeout=60)
    else:
        # Fallback to original eager loading (no manager available)
        await self.init_asr(config.asr)
        await self.init_tts(config.tts)
        await self.init_llm(...)
        await self.init_vad(config.vad)

    # Local LLM, memory, emotion analyzer always load directly
    await self.init_local_llm(config.local_llm, app_config=config)
    await self.init_audio_processor()
    await self.init_memory()
    await self.init_emotion_analyzer(config)
    await self._preload_tokenizers()

    logger.info(f"[{self.session_id}] Services loaded")
```

**Step 3:** Run existing tests to verify no regression

Run: `pytest tests/core/test_service_context.py -v`
Expected: PASS (or note pre-existing failures)

**Step 4: Commit**

```bash
git add src/animetta/core/service_context.py
git commit -m "refactor: ServiceContext uses ModelLoadingManager for coordinated loading"
```

---

### Task 8: Register services with ModelLoadingManager at server startup

**Files:**
- Modify: `src/animetta/orchestration/server/websocket.py`
- Modify: `src/animetta/core/service_context.py` (touch)

**Step 1: Write test for service registration**

```python
@pytest.mark.asyncio
async def test_service_registration():
    from anima.orchestration.server.websocket import WebSocketServer

    server = WebSocketServer(config=MagicMock())
    await server.start()

    status = server.model_manager.get_status()
    assert "asr" in status
    assert "tts" in status
    assert "llm" in status
    assert "vad" in status
```

**Step 2: Register services with manager**

In `websocket.py`, add a method `_register_services_with_manager()`:

```python
async def _register_services_with_manager(self, config):
    """Register all service loaders with ModelLoadingManager"""
    from anima.config import AppConfig

    # Create service instances
    asr_engine = ASRFactory.create(...)
    tts_engine = TTSFactory.create(...)
    llm_engine = LLMFactory.create_from_config(...)
    vad_engine = VADFactory.create_from_config(...)

    # Register with manager for coordinated warmup
    if hasattr(asr_engine, 'preload'):
        self.model_manager.register("asr", asr_engine.preload, "asr")
    if hasattr(tts_engine, 'preload'):
        self.model_manager.register("tts", tts_engine.preload, "tts")
    if hasattr(llm_engine, 'preload'):
        self.model_manager.register("llm", llm_engine.preload, "llm")
    if hasattr(vad_engine, 'preload'):
        self.model_manager.register("vad", vad_engine.preload, "vad")
```

**Step 3:** Commit

```bash
git add src/animetta/orchestration/server/websocket.py src/animetta/core/service_context.py
git commit -m "feat: register all model services with ModelLoadingManager"
```

---

### Task 9: Add warmup call to server startup

**Files:**
- Modify: `src/animetta/core/socketio_server.py`

**Step 1: Implement warmup**

In `socketio_server.py`, add warmup call in the server startup flow:

```python
def run_server():
    # ... existing code ...
    _server = create_server(global_config)
    _server.set_user_settings(user_settings)

    # Start background warmup (non-blocking - models load while server accepts connections)
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(_server.model_manager.warmup())
    # Note: This runs the warmup in the event loop alongside uvicorn
    # Services will be ready by the time the first user sends a message

    # ... register cleanup ...
    uvicorn.run(...)
```

For the ASGI mode (factory path), modify `get_asgi_app()`:
```python
def get_asgi_app():
    global _server, asgi_app, global_config, user_settings
    if asgi_app is None:
        _server = create_server(global_config)
        _server.set_user_settings(user_settings)

        # Start warmup in background
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_server.model_manager.warmup())
            else:
                loop.create_task(_server.model_manager.warmup())
        except RuntimeError:
            pass

        asgi_app = _server.get_app()
    return asgi_app
```

**Step 2:** Verify no startup crash

Run: `python -c "from anima.core.socketio_server import get_asgi_app; print('OK')"`
Expected: No crash, models start warming in background

**Step 3: Commit**

```bash
git add src/animetta/core/socketio_server.py
git commit -m "feat: add model warmup on server startup"
```

---

### Task 10: Remove ad-hoc preload from ServiceContext (cleanup)

**Files:**
- Modify: `src/animetta/core/service_context.py:129-140`
- Remove `_preload_asr_background()` method

**Step 1: Remove the fire-and-forget preload**

In `service_context.py`:
- Remove `_preload_asr_background()` method (lines 134-140)
- Remove the `asyncio.create_task(self._preload_asr_background())` call in `init_asr()` (lines 129-132)
- These are now handled by `ModelLoadingManager.warmup()`

```python
async def init_asr(self, asr_config: ASRConfig) -> None:
    if self.asr_engine is not None:
        return

    provider = asr_config.type
    logger.info(f"[{self.session_id}] Initializing ASR: {provider}/{asr_config.model}")

    self.asr_engine = ASRFactory.create(...)

    # Note: preload is now handled by ModelLoadingManager.warmup()
    # The old _preload_asr_background() has been removed
```

**Step 2:** Run test to verify

Run: `pytest tests/core/test_service_context.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/animetta/core/service_context.py
git commit -m "refactor: remove ad-hoc ASR preload (replaced by ModelLoadingManager)"
```

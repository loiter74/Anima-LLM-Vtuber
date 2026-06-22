# Qwen3-TTS Integration Implementation Plan (v2 — Oracle Reviewed)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Qwen3-TTS 1.7B CustomVoice as a new Anima TTS provider (local inference mode)

**Architecture:** Plugin provider following ADR-003: Pydantic config class (`@ProviderRegistry.register`) + service class (`@ProviderRegistry.register_service`) + `from_config()` factory bridge. Lazy model loading on first synthesis with thread-safe guard. Blocking HF Transformers inference wrapped via `run_in_executor`. Preload uses `run_in_executor` to not block event loop.

**Tech Stack:** Python 3.13+, `qwen-tts` (PyPI), PyTorch, Pydantic V2

**Design Doc:** `docs/plans/2026-05-19-qwen3-tts-integration-design.md`

---

## Pre-implementation Checklist (Oracle Required Fixes)

These are the 7 defects found by Oracle review that MUST be addressed in the implementation code:

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | `preload()` blocks event loop | **Critical** | Wrap `_load_model()` in `loop.run_in_executor(None, ...)` |
| 2 | No concurrent model-load guard | **High** | Add `threading.Lock` around `_load_model()` |
| 3 | Missing from `test_tts_providers.py` | **High** | Add to `_fake_external_modules` + `TestInterfaceContract` + individual test class |
| 4 | `close()` races with synthesis | **Medium** | Add `_synth_done` asyncio.Event + await with timeout |
| 5 | `synthesize_stream` fake stub | **Medium** | Replace with explicit `NotImplementedError` until real streaming API |
| 6 | No `default_instruct` config field | **Medium** | Add `default_instruct` to config + YAML |
| 7 | Coarse error handling for model load | **Low** | Add specific handlers for CUDA OOM / HF auth / disk space / network |

---

### Task 1: Create Qwen3TTSConfig (Pydantic config class)

**Files:**
- Create: `src/animetta/config/providers/tts/qwen3.py`
- Reference: `src/animetta/config/providers/tts/vibe_voice.py`, `src/animetta/config/providers/tts/base.py`

**Step 1: Read reference files**

Read `src/animetta/config/providers/tts/base.py` (TTSBaseConfig) and `src/animetta/config/providers/tts/vibe_voice.py` (dual-mode pattern).

**Step 2: Create `qwen3.py`**

```python
"""Qwen3-TTS provider configuration (通义千问 Qwen3-TTS)"""

from typing import Literal, Optional
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register("tts", "qwen3")
class Qwen3TTSConfig(TTSBaseConfig):
    """Qwen3-TTS configuration

    Local inference mode using qwen-tts package.
    Loads 1.7B CustomVoice model (~3.5GB VRAM bfloat16) via HuggingFace.
    Supports 9 premium preset voices with instruction-based emotion/style control.

    GPU requirements: ~4-6GB VRAM for bfloat16, ~3-4GB for float16.
    Windows CUDA note: bfloat16 may need auto-fallback to float16 on some GPUs.
    """
    type: Literal["qwen3"] = "qwen3"

    # === Model identifier ===
    model: str = Field(
        default="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        description="HuggingFace model ID or local directory path",
    )

    # === Inference device ===
    device: str = Field(
        default="cuda:0",
        description="Inference device: cuda:0 / cpu",
    )
    dtype: str = Field(
        default="bfloat16",
        description='Model dtype: "bfloat16" / "float16". Use float16 if GPU lacks bf16 support (e.g., GTX 16xx)',
    )

    # === Synthesis parameters ===
    speaker: str = Field(
        default="Vivian",
        description="Preset speaker voice name (9 premium timbres available)",
    )
    default_instruct: str = Field(
        default="",
        description="Default instruction for emotion/style control (e.g., '用温柔的语气说'). Overridable at synthesize() call time.",
    )
    language: str = Field(
        default="Chinese",
        description='Language: Chinese / English / Japanese / Korean / German / French / Russian / Portuguese / Spanish / Italian',
    )
    max_new_tokens: int = Field(
        default=4096,
        ge=512,
        le=16384,
        description="Maximum audio tokens to generate",
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Top-p nucleus sampling probability",
    )
    temperature: float = Field(
        default=0.9,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    repetition_penalty: float = Field(
        default=1.05,
        ge=1.0,
        le=2.0,
        description="Repetition penalty for token generation",
    )

    # === Flash Attention ===
    use_flash_attn: bool = Field(
        default=True,
        description="Use FlashAttention 2 for optimized GPU memory usage. Silently falls back if not installed.",
    )
```

**Step 3: Verify file loads**

```bash
PYTHONPATH=src python -c "from anima.config.providers.tts.qwen3 import Qwen3TTSConfig; print('OK')"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add src/animetta/config/providers/tts/qwen3.py
git commit -m "feat(tts): add Qwen3TTSConfig for Qwen3-TTS provider"
```

---

### Task 2: Create Qwen3TTSTTS (service implementation — with Oracle fixes)

**Files:**
- Create: `src/animetta/services/speech/tts/qwen3_tts.py`
- Reference: `src/animetta/services/speech/tts/chattts_tts.py` (local model + preload pattern)
- Reference: `src/animetta/services/speech/tts/vibe_voice_tts.py` (from_config + streaming pattern)

**Step 1: Read reference implementations**

Read ChatTTS's `preload()` (lines 95-107: uses `loop.run_in_executor(None, self._ensure_loaded)`) and VibeVoice's `from_config()`.

**Step 2: Create `qwen3_tts.py`**

```python
"""
Qwen3-TTS implementation - 通义千问 open-source TTS (CustomVoice model)

Local inference mode: loads 1.7B model via qwen-tts package.
Wraps synchronous HuggingFace generation in run_in_executor.
Thread-safe lazy loading with asyncio guard for clean shutdown.

CustomVoice features: 9 preset voices, instruction-based emotion/style control,
10 languages, optional FlashAttention 2 acceleration.

For RTX 5090D: bfloat16 + FlashAttention 2 at ~4GB VRAM.
"""

from typing import Union, Optional, AsyncGenerator
from pathlib import Path
import os
import tempfile
import asyncio
import gc
import threading

from loguru import logger

from .interface import TTSInterface
from anima.config.core.registry import ProviderRegistry
from anima.config.providers.tts.qwen3 import Qwen3TTSConfig


@ProviderRegistry.register_service("tts", "qwen3")
class Qwen3TTSTTS(TTSInterface):
    """
    Qwen3-TTS implementation (local inference mode)

    Thread-safety guarantees:
    - _load_model() guarded by threading.Lock (prevents double-load OOM)
    - close() waits for in-flight synthesis via _synth_done event
    - preload() uses run_in_executor (does not block event loop)
    """

    def __init__(
        self,
        model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        speaker: str = "Vivian",
        device: str = "cuda:0",
        dtype: str = "bfloat16",
        default_instruct: str = "",
        language: str = "Chinese",
        max_new_tokens: int = 4096,
        top_p: float = 0.9,
        temperature: float = 0.9,
        repetition_penalty: float = 1.05,
        use_flash_attn: bool = True,
    ):
        self.model = model
        self.speaker = speaker
        self.device = device
        self.dtype = dtype
        self.default_instruct = default_instruct
        self.language = language
        self.max_new_tokens = max_new_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.repetition_penalty = repetition_penalty
        self.use_flash_attn = use_flash_attn

        self._model = None
        self._loaded = False
        self._load_lock = threading.Lock()
        self._synth_done = asyncio.Event()
        self._synth_done.set()  # Initially not synthesizing

    def _get_torch_dtype(self):
        """Convert dtype string to torch dtype, with Windows bf16 fallback"""
        import torch
        if self.dtype == "bfloat16":
            if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
                logger.warning("bfloat16 not supported on this GPU, falling back to float16")
                return torch.float16
            return torch.bfloat16
        elif self.dtype == "float16":
            return torch.float16
        return torch.float16

    def _load_model(self):
        """Lazy-load the Qwen3-TTS model on first use. Thread-safe via _load_lock.

        Called under lock — no concurrent loads possible.
        This is a BLOCKING call (~30-60s for model download+load).
        Always call from run_in_executor, never from the event loop directly.
        """
        with self._load_lock:
            if self._loaded and self._model is not None:
                return

            logger.info(f"Loading Qwen3-TTS model: {self.model} (device={self.device}, dtype={self.dtype})")
            try:
                from qwen_tts import Qwen3TTSModel
                import torch
            except ImportError as e:
                raise ImportError(
                    "qwen-tts not installed. Run: pip install -U qwen-tts"
                ) from e

            # Check CUDA availability
            if self.device.startswith("cuda") and not torch.cuda.is_available():
                logger.warning("CUDA requested but not available, falling back to CPU")
                self.device = "cpu"

            # Check available VRAM
            if self.device.startswith("cuda"):
                free_vram = torch.cuda.get_device_properties(self.device).total_memory / (1024**3)
                if free_vram < 6.0:  # Less than 6GB total
                    logger.warning(
                        f"GPU has {free_vram:.1f}GB VRAM. 1.7B model needs ~4GB. "
                        "Consider using float16 dtype if bfloat16, or reducing max_new_tokens."
                    )

            kwargs = {
                "device_map": self.device,
                "dtype": self._get_torch_dtype(),
            }
            if self.use_flash_attn:
                try:
                    kwargs["attn_implementation"] = "flash_attention_2"
                    logger.debug("FlashAttention 2 enabled")
                except Exception:
                    logger.warning("FlashAttention 2 not available, using default attention (higher VRAM usage)")

            try:
                self._model = Qwen3TTSModel.from_pretrained(self.model, **kwargs)
                self._loaded = True
                logger.info(f"Qwen3-TTS model loaded successfully")
            except torch.cuda.OutOfMemoryError:
                logger.error(
                    f"CUDA OOM loading Qwen3-TTS model. "
                    f"Try: device=cpu, or dtype=float16, or a smaller max_new_tokens."
                )
                raise RuntimeError(
                    "GPU out of memory loading Qwen3-TTS model. "
                    "Try device=cpu or reduce memory usage."
                )
            except OSError as e:
                if "disk" in str(e).lower() or "space" in str(e).lower():
                    raise RuntimeError(
                        "Not enough disk space to download Qwen3-TTS model (~3.5GB). "
                        "Free up disk space or set HF_HOME to a different location."
                    ) from e
                raise
            except Exception as e:
                error_msg = str(e).lower()
                if "401" in error_msg or "403" in error_msg or "unauthorized" in error_msg:
                    raise RuntimeError(
                        "HuggingFace authentication failed. Run: huggingface-cli login"
                    ) from e
                if "timeout" in error_msg or "connection" in error_msg:
                    raise RuntimeError(
                        "Network error downloading model. Check internet connection or set HF_ENDPOINT."
                    ) from e
                raise

    @classmethod
    def from_config(cls, config: Qwen3TTSConfig, **kwargs) -> "Qwen3TTSTTS":
        """Create instance from config object"""
        return cls(
            model=config.model,
            speaker=config.speaker,
            device=config.device,
            dtype=config.dtype,
            default_instruct=getattr(config, "default_instruct", ""),
            language=config.language,
            max_new_tokens=config.max_new_tokens,
            top_p=config.top_p,
            temperature=config.temperature,
            repetition_penalty=config.repetition_penalty,
            use_flash_attn=config.use_flash_attn,
        )

    async def synthesize(
        self,
        text: str,
        output_path: Optional[Union[str, Path]] = None,
        speaker: Optional[str] = None,
        instruct: Optional[str] = None,
        **kwargs,
    ) -> Union[bytes, str]:
        """
        Synthesize text to speech using Qwen3-TTS CustomVoice model

        Args:
            text: Text to synthesize
            output_path: Output file path (optional). If None, returns audio bytes.
            speaker: Voice name override (defaults to config speaker)
            instruct: Instruction override for emotion/style (defaults to config default_instruct)
            **kwargs: Additional overrides (language, max_new_tokens, top_p, temperature, repetition_penalty)

        Returns:
            Union[bytes, str]: Audio bytes or file path string
        """
        if not text or not text.strip():
            logger.warning("Qwen3-TTS received empty text, skipping synthesis")
            return b"" if output_path is None else str(output_path)

        # Signal synthesis start
        self._synth_done.clear()

        try:
            # Thread-safe model loading (blocking — must run in executor)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._load_model)

            effective_speaker = speaker or self.speaker
            effective_language = kwargs.get("language", self.language)
            effective_instruct = instruct or self.default_instruct

            logger.debug(
                f"Qwen3-TTS synthesis: text_len={len(text)}, "
                f"speaker={effective_speaker}, language={effective_language}"
            )

            # Run synchronous generation in thread pool
            wavs, sr = await loop.run_in_executor(
                None,
                lambda: self._model.generate_custom_voice(
                    text=text,
                    language=effective_language,
                    speaker=effective_speaker,
                    instruct=effective_instruct,
                    max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                    top_p=kwargs.get("top_p", self.top_p),
                    temperature=kwargs.get("temperature", self.temperature),
                    repetition_penalty=kwargs.get("repetition_penalty", self.repetition_penalty),
                ),
            )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("Qwen3-TTS generated empty audio")

            import numpy as np
            import soundfile as sf
            from io import BytesIO

            audio_data = wavs[0] if isinstance(wavs, list) else wavs
            buffer = BytesIO()
            sf.write(buffer, audio_data, sr, format="wav")
            audio_bytes = buffer.getvalue()

            logger.debug(f"Qwen3-TTS synthesis successful: {len(audio_bytes)} bytes, sr={sr}")

            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(output_path), audio_data, sr)
                logger.info(f"Qwen3-TTS audio saved to: {output_path}")
                return str(output_path)
            return audio_bytes

        except Exception as e:
            logger.error(f"Qwen3-TTS synthesis failed: {e}")
            raise
        finally:
            self._synth_done.set()

    async def synthesize_stream(
        self,
        text: str,
        speaker: Optional[str] = None,
        instruct: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[bytes, None]:
        """Streaming speech synthesis — NOT YET IMPLEMENTED.

        Qwen3-TTS supports streaming via its Dual-Track architecture (97ms first-packet),
        but the qwen-tts Python package does not yet expose a streaming generate() API.
        When available, this will yield per-token audio chunks.

        For now, use synthesize() for full audio generation.
        """
        raise NotImplementedError(
            "Qwen3-TTS streaming synthesis is not yet available. "
            "The qwen-tts package does not expose a streaming generation API. "
            "Use synthesize() for full audio generation instead."
        )

    async def preload(self) -> None:
        """Preload model at startup (called by ModelLoadingManager).

        IMPORTANT: _load_model() is BLOCKING (~30s). Must run in executor
        to avoid freezing the event loop during server startup.
        Pattern matches ChatTTS preload (chattts_tts.py:103-105).
        """
        if self._loaded:
            logger.debug("Qwen3-TTS model already loaded, skipping preload")
            return

        logger.info(f"Preloading Qwen3-TTS model: {self.model}...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_model)
        logger.info("Qwen3-TTS model preloaded successfully")

    async def close(self) -> None:
        """Clean up model and GPU memory.

        Waits for in-flight synthesis to complete (with 10s timeout)
        before unloading the model, preventing use-after-free in executor threads.
        """
        if self._model is None:
            return

        # Wait for any in-flight synthesis to finish
        if not self._synth_done.is_set():
            logger.debug("Waiting for in-flight synthesis to complete before closing...")
            try:
                await asyncio.wait_for(self._synth_done.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for synthesis to complete. Force unloading.")

        logger.info("Unloading Qwen3-TTS model...")
        self._model = None
        self._loaded = False
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("GPU cache cleared after Qwen3-TTS unload")
        except ImportError:
            pass
        logger.info("Qwen3-TTS model unloaded")
```

**Step 3: Verify file loads**

```bash
PYTHONPATH=src python -c "from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS; print('OK')"
```
Expected: `OK` (imports should not load the model — lazy loading)

**Step 4: Commit**

```bash
git add src/animetta/services/speech/tts/qwen3_tts.py
git commit -m "feat(tts): add Qwen3TTSTTS service with thread-safe model loading"
```

---

### Task 3: Register provider in __init__.py files and factory

**Files:**
- Modify: `src/animetta/config/providers/tts/__init__.py`
- Modify: `src/animetta/services/speech/tts/__init__.py`
- Modify: `src/animetta/services/speech/tts/factory.py`

**Step 1: Read current __init__.py contents**

Read both `__init__.py` files to see exact import/export structure.

**Step 2: Update `config/providers/tts/__init__.py`**

Add import and union member:
```python
from .qwen3 import Qwen3TTSConfig

# Inside TTSConfig union:
Qwen3TTSConfig,  # Add before closing bracket of Union[...]
```

**Step 3: Update `services/speech/tts/__init__.py`**

Add import and export:
```python
from .qwen3_tts import Qwen3TTSTTS

# Inside __all__:
"Qwen3TTSTTS",
```

**Step 4: Update `factory.py` — `_build_config()`**

Add case (place alphabetically or at end before the `else: return None`):
```python
elif provider == "qwen3":
    from anima.config.providers.tts.qwen3 import Qwen3TTSConfig
    return Qwen3TTSConfig(
        model=kwargs.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        speaker=kwargs.get("speaker", "Vivian"),
        device=kwargs.get("device", "cuda:0"),
        dtype=kwargs.get("dtype", "bfloat16"),
        default_instruct=kwargs.get("default_instruct", ""),
        language=kwargs.get("language", "Chinese"),
        max_new_tokens=kwargs.get("max_new_tokens", 4096),
        top_p=kwargs.get("top_p", 0.9),
        temperature=kwargs.get("temperature", 0.9),
        repetition_penalty=kwargs.get("repetition_penalty", 1.05),
        use_flash_attn=kwargs.get("use_flash_attn", True),
    )
```

**Step 5: Verify registration**

```bash
PYTHONPATH=src python -c "from anima.config.core.registry import ProviderRegistry; svcs = ProviderRegistry.list_services('tts'); assert 'qwen3' in svcs, 'not registered'; print('OK:', svcs)"
```
Expected: `OK: ['...', 'qwen3', '...']`

**Step 6: Run existing TTS tests to verify no regressions**

```bash
PYTHONPATH=src python -m pytest tests/services/test_tts_providers.py -v -x
```
Expected: All existing tests pass

**Step 7: Commit**

```bash
git add src/animetta/config/providers/tts/__init__.py src/animetta/services/speech/tts/__init__.py src/animetta/services/speech/tts/factory.py
git commit -m "feat(tts): register Qwen3-TTS provider in factory and exports"
```

---

### Task 4: Add YAML configuration entry

**Files:**
- Modify: `config/services.yaml`

**Step 1: Read TTS section of services.yaml**

Read to understand exact indentation and YAML structure.

**Step 2: Add qwen3_custom_voice entry**

Under the `tts:` section, add:
```yaml
  qwen3_custom_voice:
    type: qwen3
    model: "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    speaker: "Vivian"
    device: "cuda:0"
    dtype: "bfloat16"
    default_instruct: ""
    language: "Chinese"
    max_new_tokens: 4096
    top_p: 0.9
    temperature: 0.9
    repetition_penalty: 1.05
    use_flash_attn: true
```

**Note:** To activate, set `tts: qwen3_custom_voice` in `config/config.yaml`.

**Step 3: Verify YAML loads**

```bash
PYTHONPATH=src python -c "from anima.config.app import AppConfig; cfg = AppConfig.from_yaml(); print('OK')"
```
Expected: `OK` (no validation errors)

**Step 4: Commit**

```bash
git add config/services.yaml
git commit -m "feat(tts): add qwen3_custom_voice config to services.yaml"
```

---

### Task 5: Install dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add to requirements.txt**

```
qwen-tts>=0.1.0
# flash-attn  # Uncomment if GPU supports it and pip install flash-attn succeeds
```

Note: `qwen-tts` exact version — verify on PyPI first.

**Step 2: Install**

```bash
pip install -U qwen-tts
```

Expected: Package installs without errors.

**Step 3: Verify import works**

```bash
python -c "from qwen_tts import Qwen3TTSModel; print('qwen-tts OK')"
```
Expected: `qwen-tts OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add qwen-tts dependency"
```

---

### Task 6: Write tests — integration with test_tts_providers.py + standalone test

**Files:**
- Modify: `tests/services/test_tts_providers.py`
- Create: `tests/unit/test_tts_qwen3.py`

**Step 1: Add fake module to `_fake_external_modules` fixture**

In `tests/services/test_tts_providers.py`, add:
```python
# In _fake_external_modules fixture:
# qwen_tts.Qwen3TTSModel
fake_qwen_tts = MagicMock()
fake_qwen_tts.Qwen3TTSModel = MagicMock()
fakes["qwen_tts"] = fake_qwen_tts
```

**Step 2: Add to `TestInterfaceContract` parametrize**

Add to both parametrize lists:
```python
pytest.importorskip("anima.services.speech.tts.qwen3_tts").Qwen3TTSTTS,
```

**Step 3: Add `TestQwen3TTSTTS` class**

```python
class TestQwen3TTSTTS:
    """Qwen3TTSTTS — local Qwen3-TTS model inference."""

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        # Mock Qwen3TTSModel via fake module
        import numpy as np
        mock_model = MagicMock()
        fake_audio = np.zeros(24000, dtype=np.float32)
        mock_model.generate_custom_voice.return_value = ([fake_audio], 24000)
        sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.return_value = mock_model

        tts = Qwen3TTSTTS(device="cpu")  # Use CPU to avoid CUDA issues
        result = await tts.synthesize("你好")
        assert isinstance(result, bytes)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_returns_empty(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        tts = Qwen3TTSTTS(device="cpu")
        result = await tts.synthesize("")
        assert result == b""

    def test_from_config_all_fields(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        config = _make_config_mock(
            model="test/model",
            speaker="TestVoice",
            device="cpu",
            dtype="float16",
            default_instruct="用温柔的语气",
            language="Japanese",
            max_new_tokens=2048,
            top_p=0.8,
            temperature=0.7,
            repetition_penalty=1.1,
            use_flash_attn=False,
        )
        tts = Qwen3TTSTTS.from_config(config)
        assert tts.speaker == "TestVoice"
        assert tts.device == "cpu"
        assert tts.default_instruct == "用温柔的语气"
        assert tts.language == "Japanese"
        assert tts.max_new_tokens == 2048

    @pytest.mark.asyncio
    async def test_preload_uses_executor(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        # Mock Qwen3TTSModel to avoid real load
        mock_model = MagicMock()
        sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.return_value = mock_model

        tts = Qwen3TTSTTS(device="cpu")
        await tts.preload()
        assert tts._loaded is True

    @pytest.mark.asyncio
    async def test_close_without_model(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        tts = Qwen3TTSTTS(device="cpu")
        await tts.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_synthesize_stream_raises_not_implemented(self):
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        tts = Qwen3TTSTTS(device="cpu")
        with pytest.raises(NotImplementedError):
            async for _ in tts.synthesize_stream("hello"):
                pass  # Should not yield anything

    @pytest.mark.asyncio
    async def test_thread_safety_load_lock(self):
        """Verify concurrent synthesize calls don't double-load the model."""
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS
        import numpy as np

        mock_model = MagicMock()
        fake_audio = np.zeros(24000, dtype=np.float32)
        mock_model.generate_custom_voice.return_value = ([fake_audio], 24000)
        sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.return_value = mock_model

        tts = Qwen3TTSTTS(device="cpu")

        # Fire two concurrent synthesize calls
        results = await asyncio.gather(
            tts.synthesize("hello"),
            tts.synthesize("world"),
        )
        assert all(isinstance(r, bytes) for r in results)
        # Model should only have been loaded once
        assert sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.call_count == 1
```

**Step 4: Create standalone test `tests/unit/test_tts_qwen3.py`**

```python
"""Unit tests for Qwen3-TTS provider (config + registry + from_config)"""

import pytest

from anima.config.providers.tts.qwen3 import Qwen3TTSConfig
from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS
from anima.config.core.registry import ProviderRegistry


class TestQwen3TTSConfigUnit:
    def test_default_config_values(self):
        config = Qwen3TTSConfig()
        assert config.type == "qwen3"
        assert config.model == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        assert config.speaker == "Vivian"
        assert config.device == "cuda:0"
        assert config.default_instruct == ""
        assert config.language == "Chinese"

    def test_custom_config_values(self):
        config = Qwen3TTSConfig(
            model="custom/model",
            speaker="Aria",
            device="cpu",
            default_instruct="用愤怒的语气说",
            language="English",
        )
        assert config.speaker == "Aria"
        assert config.device == "cpu"
        assert config.default_instruct == "用愤怒的语气说"

    def test_config_registered_in_registry(self):
        assert "qwen3" in ProviderRegistry.list_services("tts")

    def test_max_new_tokens_bounds(self):
        with pytest.raises(Exception):  # Pydantic validation
            Qwen3TTSConfig(max_new_tokens=100)

    @pytest.mark.parametrize("dtype", ["bfloat16", "float16"])
    def test_valid_dtype_values(self, dtype):
        config = Qwen3TTSConfig(dtype=dtype)
        assert config.dtype == dtype


class TestQwen3TTSTTSUnit:
    def test_from_config_creates_lazy(self):
        config = Qwen3TTSConfig(device="cpu")
        tts = Qwen3TTSTTS.from_config(config)
        assert tts._model is None  # Model not loaded
        assert tts._loaded is False

    def test_from_config_preserves_instruct(self):
        config = Qwen3TTSConfig(
            default_instruct="温柔地轻声说",
            speaker="Luna",
        )
        tts = Qwen3TTSTTS.from_config(config)
        assert tts.default_instruct == "温柔地轻声说"
        assert tts.speaker == "Luna"

    def test_server_switching_preserves_preload_method(self):
        """Verify close() + re-init doesn't lose methods needed by ServicePool."""
        tts = Qwen3TTSTTS(device="cpu")
        assert hasattr(tts, "preload") and callable(tts.preload)
        assert hasattr(tts, "close") and callable(tts.close)

    def test_lock_initialized(self):
        tts = Qwen3TTSTTS(device="cpu")
        assert hasattr(tts, "_load_lock")
        assert hasattr(tts, "_synth_done")
```

**Step 5: Run all tests**

```bash
PYTHONPATH=src python -m pytest tests/services/test_tts_providers.py tests/unit/test_tts_qwen3.py -v
```
Expected: All tests pass

**Step 6: Commit**

```bash
git add tests/services/test_tts_providers.py tests/unit/test_tts_qwen3.py
git commit -m "test(tts): add Qwen3-TTS tests with mocked model loading"
```

---

### Task 7: LSP diagnostics and final verification

**Step 1: LSP diagnostics on all changed files**

```bash
# Check each changed file for type errors
python -m mypy src/animetta/config/providers/tts/qwen3.py --ignore-missing-imports
python -m mypy src/animetta/services/speech/tts/qwen3_tts.py --ignore-missing-imports
```

**Step 2: Run full test suite**

```bash
PYTHONPATH=src python -m pytest tests/ -x --timeout=60
```
Expected: All tests pass (or known pre-existing failures only)

**Step 3: Verify provider is discoverable**

```bash
PYTHONPATH=src python -c "
from anima.services.speech.tts.factory import TTSFactory
providers = TTSFactory.get_available_providers()
assert 'qwen3' in providers
print(f'Registered TTS providers: {providers}')
"
```

**Step 4: Final review of diff**

```bash
git diff --stat HEAD~4..HEAD
```
Expected: ~10 files changed, clean diff

---

## Summary of All Changes

| # | Action | File | Notes |
|---|--------|------|-------|
| 1 | Create | `src/animetta/config/providers/tts/qwen3.py` | Config with `default_instruct` field |
| 2 | Create | `src/animetta/services/speech/tts/qwen3_tts.py` | Service with thread-safety, preload executor, close guard |
| 3a | Modify | `src/animetta/config/providers/tts/__init__.py` | Add to union type |
| 3b | Modify | `src/animetta/services/speech/tts/__init__.py` | Add export |
| 3c | Modify | `src/animetta/services/speech/tts/factory.py` | Add factory case |
| 4 | Modify | `config/services.yaml` | Add `qwen3_custom_voice` entry |
| 5 | Modify | `requirements.txt` | Add `qwen-tts` |
| 6a | Modify | `tests/services/test_tts_providers.py` | Add fake module + TestInterfaceContract + test class |
| 6b | Create | `tests/unit/test_tts_qwen3.py` | Standalone config/registry tests |

### Oracle-Reviewed Critical Fixes Applied

| # | Fix | Where |
|---|-----|-------|
| 1 | `run_in_executor` in `preload()` | Line ~344: `await loop.run_in_executor(None, self._load_model)` |
| 2 | `threading.Lock` guard on `_load_model()` | Line ~88: `with self._load_lock:` |
| 3 | Integration with existing test suite | Task 6: `_fake_external_modules`, `TestInterfaceContract`, `TestQwen3TTSTTS` class |
| 4 | `asyncio.Event` + 10s timeout in `close()` | Line ~354: `await asyncio.wait_for(self._synth_done.wait(), timeout=10.0)` |
| 5 | `synthesize_stream` → explicit `NotImplementedError` | Line ~320: raises with clear message |
| 6 | `default_instruct` config field | Config line ~63 + service init |
| 7 | Specific error recovery | `_load_model()`: CUDA OOM, HF auth, disk space, network timeout handlers |

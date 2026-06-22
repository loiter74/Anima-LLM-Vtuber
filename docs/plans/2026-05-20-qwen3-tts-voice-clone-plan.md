# Qwen3-TTS Voice Clone for 久远寺有珠 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add zero-shot voice clone path to Qwen3TTSTTS via `generate_voice_clone()`, enabling 久远寺有珠 voice synthesis using reference audio — no training required.

**Architecture:** Extend existing `Qwen3TTSTTS` with config-driven dispatch: if `ref_audio_path` is set, use `generate_voice_clone()` (with lazy prompt caching); otherwise fall through to existing `generate_custom_voice()`. New config fields on `Qwen3TTSConfig`, new service entry in `services.yaml`.

**Tech Stack:** Python 3.13+, qwen-tts 0.1.1, Pydantic v2, asyncio, pytest + MagicMock

**Design Doc:** `docs/plans/2026-05-20-qwen3-tts-voice-clone-design.md`

---

### Task 1: Add voice clone fields to Qwen3TTSConfig

**Files:**
- Modify: `src/animetta/config/providers/tts/qwen3.py:21-80`

**Step 1: Add fields**

After `use_flash_attn` (line 80), add:

```python
    # === Voice Clone ===
    ref_audio_path: str | None = Field(
        default=None,
        description="Path to reference audio WAV for voice clone mode. When set, synthesize() uses generate_voice_clone() instead of generate_custom_voice().",
    )
    ref_text: str | None = Field(
        default=None,
        description="Reference transcript for ICL mode (required when x_vector_only=False). Optional when x_vector_only=True.",
    )
    x_vector_only: bool = Field(
        default=True,
        description="If True, use speaker embedding only (no ref_text needed). If False, ICL mode with ref_text + speech codes.",
    )
```

Update the class docstring (line 16) to mention voice clone support:

```
Supports 9 preset voices + zero-shot voice clone via ref_audio_path.
```

**Step 2: Run existing tests to confirm no regression**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_tts_qwen3.py -v
```

Expected: All 7 tests PASS (new fields default to None, don't break existing behavior).

**Step 3: Commit**

```bash
git add src/animetta/config/providers/tts/qwen3.py
git commit -m "feat(qwen3-tts): add voice clone config fields to Qwen3TTSConfig"
```

QA: New fields have correct defaults (`None`, `None`, `True`), existing tests pass.

---

### Task 2: Add voice clone synthesis path to Qwen3TTSTTS

**Files:**
- Modify: `src/animetta/services/speech/tts/qwen3_tts.py`

**Step 1: Add voice clone constructor params**

In `__init__()` signature (line 52), add after `use_flash_attn: bool = True`:

```python
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        x_vector_only: bool = True,
```

In `__init__()` body (after line 64), add:

```python
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.x_vector_only = x_vector_only
        # Voice clone prompt cache (lazy, invalidated on close/model reload)
        self._voice_clone_prompt: list | None = None
```

**Step 2: Add `_build_voice_clone_prompt()` method**

Add after `_load_model()` (before `from_config()`):

```python
    def _build_voice_clone_prompt(self):
        """Build and cache voice clone prompt from reference audio.
        
        Thread-safe: called under _load_lock after model is loaded.
        Returns cached prompt on subsequent calls.
        """
        if self._voice_clone_prompt is not None:
            return self._voice_clone_prompt
        
        if not self.ref_audio_path:
            raise ValueError("ref_audio_path must be set for voice clone mode")
        
        import os
        if not os.path.exists(self.ref_audio_path):
            raise FileNotFoundError(f"Reference audio not found: {self.ref_audio_path}")
        
        logger.info(f"Building voice clone prompt from: {self.ref_audio_path}")
        self._voice_clone_prompt = self._model.create_voice_clone_prompt(
            ref_audio=self.ref_audio_path,
            ref_text=self.ref_text,
            x_vector_only_mode=self.x_vector_only,
        )
        logger.debug(f"Voice clone prompt cached ({len(self._voice_clone_prompt)} items)")
        return self._voice_clone_prompt
```

**Step 3: Add dispatch logic to `synthesize()`**

In `synthesize()` method, after `effective_instruct` line (line 224), replace the `wavs, sr = ...` block with dispatch:

```python
            if self.ref_audio_path:
                # Voice clone mode
                prompt = self._build_voice_clone_prompt()
                wavs, sr = await loop.run_in_executor(
                    None,
                    lambda: self._model.generate_voice_clone(
                        text=text,
                        language=effective_language,
                        voice_clone_prompt=prompt,
                        max_new_tokens=kwargs.get("max_new_tokens", self.max_new_tokens),
                        top_p=kwargs.get("top_p", self.top_p),
                        temperature=kwargs.get("temperature", self.temperature),
                        repetition_penalty=kwargs.get("repetition_penalty", self.repetition_penalty),
                    ),
                )
            else:
                # Custom voice mode (existing behavior)
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
```

**Step 4: Update `from_config()`**

In `from_config()` (line 174), add voice clone params:

```python
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
            ref_audio_path=getattr(config, "ref_audio_path", None),
            ref_text=getattr(config, "ref_text", None),
            x_vector_only=getattr(config, "x_vector_only", True),
        )
```

**Step 5: Invalidate prompt cache on `close()`**

In `close()` method, after `self._loaded = False` (line 329), add:

```python
        self._voice_clone_prompt = None  # Invalidate cached prompt
```

**Step 6: Verify with LSP diagnostics**

```bash
# Check for type errors
```

**Step 7: Commit**

```bash
git add src/animetta/services/speech/tts/qwen3_tts.py
git commit -m "feat(qwen3-tts): add voice clone synthesis path with prompt caching"
```

QA: `lsp_diagnostics` clean, code compiles without errors.

---

### Task 3: Add qwen3_voice_clone service config

**Files:**
- Modify: `config/services.yaml`

**Step 1: Add config entry**

After the `qwen3_custom_voice` block (line 216), add:

```yaml
  # Qwen3-TTS voice clone（零样本声音克隆，用久远寺有珠参考音频）
  qwen3_voice_clone:
    type: qwen3
    model: "D:/huggingface_cache/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice/snapshots/0c0e3051f131929182e2c023b9537f8b1c68adfe"
    speaker: "Vivian"                          # fallback speaker
    device: "cuda:0"
    dtype: "float16"
    default_instruct: ""
    language: "Chinese"
    max_new_tokens: 128
    top_p: 0.9
    temperature: 0.9
    repetition_penalty: 1.05
    use_flash_attn: false
    ref_audio_path: "E:/anima_data/tts_training/kuonji_arisu/training_ready/S_alice_confirmed/FGO_Myroom_01.wav"
    x_vector_only: true
```

Note: The `ref_audio_path` should point to an actual file. Verify the exact filename in `S_alice_confirmed/` before committing.

**Step 2: Verify YAML validity**

```bash
python -c "import yaml; yaml.safe_load(open('config/services.yaml')); print('YAML valid')"
```

**Step 3: Commit**

```bash
git add config/services.yaml
git commit -m "config(qwen3-tts): add qwen3_voice_clone service for 久远寺有珠 voice clone"
```

QA: YAML parses without errors, service entry has all required fields.

---

### Task 4: Unit tests for voice clone config fields

**Files:**
- Modify: `tests/unit/test_tts_qwen3.py`

**Step 1: Write the failing tests**

Add to `TestQwen3TTSConfigUnit`:

```python
    def test_voice_clone_fields_default_to_none(self):
        config = Qwen3TTSConfig()
        assert config.ref_audio_path is None
        assert config.ref_text is None
        assert config.x_vector_only is True

    def test_voice_clone_fields_custom_values(self):
        config = Qwen3TTSConfig(
            ref_audio_path="E:/test/audio.wav",
            ref_text="こんにちは",
            x_vector_only=False,
        )
        assert config.ref_audio_path == "E:/test/audio.wav"
        assert config.ref_text == "こんにちは"
        assert config.x_vector_only is False
```

Add to `TestQwen3TTSTTSUnit`:

```python
    def test_from_config_preserves_voice_clone_params(self):
        config = Qwen3TTSConfig(
            device="cpu",
            ref_audio_path="test/ref.wav",
            ref_text="hello",
            x_vector_only=False,
        )
        tts = Qwen3TTSTTS.from_config(config)
        assert tts.ref_audio_path == "test/ref.wav"
        assert tts.ref_text == "hello"
        assert tts.x_vector_only is False

    def test_voice_clone_prompt_cache_initialized(self):
        tts = Qwen3TTSTTS(device="cpu", ref_audio_path="test.wav")
        assert tts._voice_clone_prompt is None
```

**Step 2: Run tests to verify they fail (if code not yet written)**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_tts_qwen3.py -v
```

If Task 1-2 are done: 4 new tests PASS. If before Task 1-2: FAIL with AttributeError.

**Step 3: Run full existing test suite**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_tts_qwen3.py tests/services/test_tts_providers.py -v -k qwen3
```

Expected: All tests PASS, no regressions.

**Step 4: Commit**

```bash
git add tests/unit/test_tts_qwen3.py
git commit -m "test(qwen3-tts): add unit tests for voice clone config and from_config"
```

QA: All tests pass including new voice clone tests.

---

### Task 5: Integration test for voice clone synthesis path

**Files:**
- Modify: `tests/services/test_tts_providers.py`

**Step 1: Write the integration test**

Add to `TestQwen3TTSTTS` class (after line 662):

```python
    @pytest.mark.asyncio
    async def test_synthesize_voice_clone_mode(self):
        """When ref_audio_path is set, synthesize() uses generate_voice_clone()."""
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS
        import os

        import numpy as np
        mock_model = MagicMock()
        fake_audio = np.zeros(24000, dtype=np.float32)
        mock_model.generate_voice_clone.return_value = ([fake_audio], 24000)
        # Mock create_voice_clone_prompt
        mock_prompt = MagicMock()
        mock_model.create_voice_clone_prompt.return_value = [mock_prompt]
        
        sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.return_value = mock_model
        
        # Use a temp file as mock reference audio
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            ref_path = f.name
        
        try:
            tts = Qwen3TTSTTS(
                device="cpu",
                ref_audio_path=ref_path,
                x_vector_only=True,
            )
            result = await tts.synthesize("テスト")
            
            # Verify voice clone was called, not custom voice
            mock_model.generate_voice_clone.assert_called_once()
            mock_model.generate_custom_voice.assert_not_called()
            assert isinstance(result, bytes)
            assert len(result) > 0
        finally:
            os.unlink(ref_path)

    @pytest.mark.asyncio
    async def test_synthesize_falls_back_to_custom_voice_without_ref_audio(self):
        """Without ref_audio_path, uses existing custom voice path."""
        from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

        import numpy as np
        mock_model = MagicMock()
        fake_audio = np.zeros(24000, dtype=np.float32)
        mock_model.generate_custom_voice.return_value = ([fake_audio], 24000)
        sys.modules["qwen_tts"].Qwen3TTSModel.from_pretrained.return_value = mock_model

        tts = Qwen3TTSTTS(device="cpu")  # No ref_audio_path
        result = await tts.synthesize("你好")

        mock_model.generate_custom_voice.assert_called_once()
        mock_model.generate_voice_clone.assert_not_called()
```

**Note**: The existing `_fake_external_modules` fixture (line 53-56) already mocks `qwen_tts.Qwen3TTSModel`. The new tests reuse this mock.

**Step 2: Run integration tests**

```bash
PYTHONPATH=src python -m pytest tests/services/test_tts_providers.py::TestQwen3TTSTTS -v
```

Expected: All Qwen3TTSTTS tests PASS, including 2 new ones (8 total).

**Step 3: Commit**

```bash
git add tests/services/test_tts_providers.py
git commit -m "test(qwen3-tts): add integration tests for voice clone synthesis path"
```

QA: `pytest tests/services/test_tts_providers.py::TestQwen3TTSTTS -v` — all tests green.

---

### Task 6: Manual QA — smoke test with real reference audio

**Prerequisites:** Qwen3-TTS model downloaded, reference audio exists at `S_alice_confirmed/`.

**Step 1: Verify reference audio exists**

```bash
ls E:/anima_data/tts_training/kuonji_arisu/training_ready/S_alice_confirmed/
```

Expected: At least one `.wav` file listed.

**Step 2: Run a quick Python smoke test**

```python
import asyncio
import soundfile as sf
from anima.services.speech.tts.qwen3_tts import Qwen3TTSTTS

async def smoke_test():
    tts = Qwen3TTSTTS(
        device="cuda:0",
        dtype="float16",
        ref_audio_path="E:/anima_data/tts_training/kuonji_arisu/training_ready/S_alice_confirmed/FGO_Myroom_01.wav",
        x_vector_only=True,
        max_new_tokens=128,
    )
    
    texts = [
        "こんにちは、私は久遠寺有珠です。",
        "今日はいい天気ですね。",
        "魔法使いの夜へようこそ。",
    ]
    
    for i, text in enumerate(texts):
        print(f"\n[{i+1}/{len(texts)}] Synthesizing: {text}")
        audio = await tts.synthesize(text)
        output_path = f"smoke_test_output_{i+1}.wav"
        with open(output_path, "wb") as f:
            f.write(audio)
        print(f"  Saved: {output_path} ({len(audio)} bytes)")
    
    await tts.close()

asyncio.run(smoke_test())
```

**Step 3: Evaluate outputs**

- Play each WAV file
- **Pass criteria**: Voice sounds recognizably like 久远寺有珠 (花澤香菜), not like Vivian
- **Acceptable**: Some artifacts OK for zero-shot; quality improves with ICL mode and more reference audio
- If voice is clearly wrong (sounds like Vivian or garbled): investigate `create_voice_clone_prompt` behavior, try a different reference audio file

**Step 4: Document result**

Note in plan or commit message: "Manual QA: voice clone produces [acceptable/excellent/poor] 久远寺有珠 voice quality. [Observations]."

---

### Task 7: Final regression check

**Step 1: Run full Qwen3 test suite**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_tts_qwen3.py tests/services/test_tts_providers.py -v -k qwen3
```

Expected: All 15+ tests PASS.

**Step 2: Type check changed files**

```bash
mypy src/animetta/config/providers/tts/qwen3.py src/animetta/services/speech/tts/qwen3_tts.py --ignore-missing-imports
```

Expected: No new errors.

**Step 3: Lint**

```bash
ruff check src/animetta/config/providers/tts/qwen3.py src/animetta/services/speech/tts/qwen3_tts.py
```

Expected: Clean.

**Step 4: Commit final state**

```bash
git add -A
git commit -m "chore(qwen3-tts): final verification — all tests pass, type check clean"
```

QA: Full test suite green, type check clean, lint clean, manual smoke test result documented.

---

## Summary

| Task | Files | New Code |
|------|-------|----------|
| 1. Config fields | `qwen3.py` | +12 lines |
| 2. Voice clone path | `qwen3_tts.py` | +60 lines |
| 3. Service config | `services.yaml` | +17 lines |
| 4. Unit tests | `test_tts_qwen3.py` | +25 lines |
| 5. Integration tests | `test_tts_providers.py` | +60 lines |
| 6. Manual QA | n/a | smoke test script |
| 7. Regression | n/a | commands only |

**Total estimated effort:** 7 commits, ~175 lines new code, ~30 minutes.

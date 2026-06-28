# Qwen3-TTS Voice Clone for 久远寺有珠 — Quick Validation Design

**Date:** 2026-05-20
**Status:** Approved
**Character:** 久远寺有珠 (Alice Kuonji, voiced by 花澤香菜)

## Overview

Add a zero-shot voice clone path to the existing `Qwen3TTSTTS` service using `qwen-tts`'s `generate_voice_clone()` method. This enables immediate voice cloning of 久远寺有珠 using a reference audio sample, with zero training required. Serves as a quick validation before committing to full fine-tuning.

## Architecture & Data Flow

```
Anima TTS Service (qwen3_tts.py)
├── generate_custom_voice()  ← existing (preset speakers: Vivian, Aria, etc.)
└── generate_voice_clone()   ← NEW (reference audio)
     ├── create_voice_clone_prompt(ref_audio)
     │    ├── extract speaker embedding (x_vector)
     │    └── optional: extract speech codes (ICL)
     └── model.generate(voice_clone_prompt=...)
          └── returns WAV numpy array
```

**Reference audio source:** `E:\anima_data\tts_training\kuonji_arisu\training_ready\S_alice_confirmed\` (highest quality S-grade samples).

## Implementation Changes

### Files to Modify

| File | Change |
|------|--------|
| `src/animetta/config/providers/tts/qwen3.py` | Add `voice_clone` config fields: `ref_audio_path`, `x_vector_only`, `ref_text` |
| `src/animetta/services/speech/tts/qwen3_tts.py` | Add `_synthesize_via_voice_clone()` method, wire into `synthesize()` dispatch |
| `config/services.yaml` | Add `qwen3_voice_clone` service entry pointing to reference audio |

### Config Fields (Qwen3TTSConfig)

```python
# Voice clone settings (optional — when set, uses generate_voice_clone)
ref_audio_path: str | None = None    # Path to reference WAV
ref_text: str | None = None          # Reference transcript (optional if x_vector_only)
x_vector_only: bool = True           # Default: speaker embedding only, no ICL
```

### Dispatch Logic

```python
if self.config.ref_audio_path:
    return await self._synthesize_via_voice_clone(text)
else:
    return await self._synthesize_via_custom_voice(text)  # existing
```

### Lazy Prompt Caching

`create_voice_clone_prompt()` is expensive. Cache it once on first call, reuse for subsequent requests. Invalidate on `close()` / model re-init.

## Error Handling & Edge Cases

| Scenario | Handling |
|----------|----------|
| `ref_audio_path` missing | `FileNotFoundError` → `TTSException` |
| Reference audio too short/silent | Warn, fallback to `generate_custom_voice()` |
| `x_vector_only=False` without `ref_text` | `ValueError` |
| Model not yet loaded | Same lazy-load pattern (`_ensure_model()`) |
| OOM / CUDA error | Catch `RuntimeError`, fallback to `generate_custom_voice()` |
| Prompt cache stale after reload | Invalidate on `close()` |

## QA Verification

| Test | How |
|------|-----|
| Smoke test | `generate_voice_clone()` → save WAV → play |
| Latency | Cached prompt <200ms |
| Fallback | Delete ref_audio → verify falls back to Vivian |
| Regression | `pytest tests/services/test_tts_providers.py -v -k qwen3` |

## Scope Boundary

**IN scope (quick validation):**
- `generate_voice_clone()` path in `Qwen3TTSTTS`
- Config-driven: `ref_audio_path` toggles voice clone mode
- Lazy prompt caching
- Manual QA: 3-5 test sentences, verify voice similarity

**OUT of scope:**
- Training/fine-tuning (zero-shot only)
- `config/personas/arisu.yaml` persona file
- ICL mode (`x_vector_only=False`) — requires accurate transcription
- Multi-reference averaging
- Streaming voice clone
- Frontend UI changes

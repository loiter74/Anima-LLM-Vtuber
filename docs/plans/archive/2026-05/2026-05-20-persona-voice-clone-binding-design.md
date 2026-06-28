# Persona ↔ Voice Clone Binding — Design (MVP)

**Date:** 2026-05-20
**Status:** Draft — for future implementation
**Depends on:** `docs/plans/archive/2026-05/2026-05-20-qwen3-tts-voice-clone-design.md` (completed)

## Overview

Bind cloned voices to conversation personas. When user switches persona in UI, the TTS voice hot-swaps to the corresponding cloned voice. MVP: only 久远寺有珠 has a cloned voice; other personas use default TTS.

## Architecture

```
Persona YAML                    services.yaml
┌──────────────────┐           ┌──────────────────────┐
│ arisu.yaml        │           │ persona_voices:       │
│   tts_voice: arisu│──────────►│   arisu:              │
│                    │           │     ref_audio_path:..│
└──────────────────┘           │     x_vector_only:true│
                                └──────────────────────┘
                                         │
PersonaPanel.vue ──► persona_handlers.py │
  socket.emit          on_set_persona()  │
  {persona:'arisu'}    │                 │
                       ├─ update LLM prompt
                       └─ tts.set_voice_clone(config)
                                │
                          Qwen3TTSTTS (singleton)
                          ├─ _voice_clone_prompt ← cached
                          └─ synthesize() → cloned voice
```

## Key Changes

| File | Change |
|------|--------|
| `config/personas/arisu.yaml` | NEW — persona with `tts_voice: arisu` |
| `src/animetta/config/persona/base.py` | Add `tts_voice: Optional[str]` field |
| `config/services.yaml` | Add `persona_voices.arisu` section |
| `src/animetta/services/speech/tts/qwen3_tts.py` | Add `set_voice_clone(ref_audio)` method |
| `src/animetta/orchestration/server/handlers/persona_handlers.py` | Call `tts.set_voice_clone()` on switch |
| `frontend/.../PersonalityPanel.vue` | Fix socket event key (`persona` → `persona_name`) |

## Scope

**MVP:** Arisu only. Hot-swap prompt in singleton TTS engine. No multi-engine, no preloading.

**Future:** Multiple cloned voices → per-persona TTS engine pool.

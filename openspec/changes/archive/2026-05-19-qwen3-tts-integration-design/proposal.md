# Qwen3-TTS Integration Design

**Date:** 2026-05-19
**Status:** Approved
**Model:** Qwen3-TTS-12Hz-1.7B-CustomVoice (通义千问)
**Deployment:** Local inference (in-process model loading)

## Overview

Integrate Alibaba Qwen team's open-source Qwen3-TTS 1.7B CustomVoice model as a new TTS provider in Anima. The model supports 9 premium preset voices, instruction-based emotion/style control, streaming generation (97ms first-packet latency), and 10 languages.

## Architecture

### Data Flow

```
tts_node → service_context.tts_engine.synthesize(text)
    → Qwen3TTSTTS.synthesize(text, speaker="Vivian", instruct="")
        → Qwen3TTSModel.generate_custom_voice(text, language, speaker, instruct)
            → (wavs: List[np.ndarray], sr: int)
    → bytes / file path
```

### Lifecycle

```
ServicePool.init()
    → ServiceContext.init_tts(config)
        → TTSFactory.create("qwen3", ...)
            → Qwen3TTSConfig(type="qwen3", ...)
            → ProviderRegistry.create_service("tts", config)
                → Qwen3TTSTTS.from_config(config)
                    → Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
```

## Files to Create

### 1. `src/animetta/config/providers/tts/qwen3.py`

Pydantic config class following `vibe_voice.py` pattern:

```python
@ProviderRegistry.register("tts", "qwen3")
class Qwen3TTSConfig(TTSBaseConfig):
    type: Literal["qwen3"] = "qwen3"
    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    speaker: str = "Vivian"           # Preset voice name
    device: str = "cuda:0"            # Inference device
    dtype: str = "bfloat16"           # bfloat16 / float16
    language: str = "Chinese"         # Language code
    max_new_tokens: int = 4096        # Max audio tokens
    top_p: float = 0.9
    temperature: float = 0.9
    repetition_penalty: float = 1.05
    streaming: bool = True            # Enable streaming output
```

### 2. `src/animetta/services/speech/tts/qwen3_tts.py`

Service class following `chattts_tts.py` local inference pattern:

- **Lazy loading**: Model loaded on first `synthesize()` call, not at init
- **Async wrapper**: Synchronous `Qwen3TTSModel.generate_custom_voice()` called via `run_in_executor`
- **Streaming support**: `synthesize_stream()` for token-level audio output
- **Cleanup**: `close()` releases model, clears GPU cache
- **Decorator**: `@ProviderRegistry.register_service("tts", "qwen3")`
- **Factory method**: `from_config(config)` classmethod

## Files to Modify

### 3. `src/animetta/config/providers/tts/__init__.py`
- Import `Qwen3TTSConfig`
- Add to `TTSConfig` union type

### 4. `src/animetta/services/speech/tts/__init__.py`
- Import `Qwen3TTSTTS`
- Add to `__all__`

### 5. `src/animetta/services/speech/tts/factory.py`
- Add `elif provider == "qwen3":` block in `_build_config()`

### 6. `config/services.yaml`
- Add `qwen3_custom_voice` entry under `tts:` section

## Dependencies

```bash
pip install -U qwen-tts
pip install -U flash-attn --no-build-isolation  # optional, for perf
```

`qwen-tts` pulls in torch, transformers, and other dependencies. Model weights (~3.5GB for 1.7B) auto-downloaded from HuggingFace on first load.

## Preset Voices (CustomVoice 1.7B)

9 premium timbres available via `speaker` parameter. `instruct` parameter controls emotion/style:
- "用愤怒的语气说"
- "温柔地轻声说"
- "欢快地朗读"
- etc.

## Multi-language Support

10 languages: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian.

## Testing

- Unit test: mock `Qwen3TTSModel`, verify config → service creation
- Integration test: short synthesis with small model (requires GPU)
- Follow existing test patterns in `tests/`

## utw-loop

The `/ulw-loop` command (OpenCode built-in) will be used to drive the implementation in an iterative ultrawork loop, ensuring exhaustive verification at each step.

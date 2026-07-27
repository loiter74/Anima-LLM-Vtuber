## Why

Hiyori currently treats nine full-body motions as idle choices, so ordinary spoken replies can trigger arbitrary large gestures whose timing and meaning do not match the audio. The response LLM needs a bounded semantic performance vocabulary while the renderer needs deterministic ownership of idle motion, facial parameters, accents, and lip sync.

## What Changes

- Add a versioned semantic performance plan with seven base expressions, two intensities, five optional accents, and safe fallback behavior.
- Reuse the existing response LLM through one leading marker; no extra director-model call is introduced.
- Deliver the validated semantic plan with the audio-start contract so expressions begin with actual playback.
- Keep Hiyori motion `m01` as the only calm idle and exclude unreviewed `m02`–`m10` motions from LLM control.
- Add a deterministic frontend performance controller that composes model motion, facial overlays, accents, and lip sync without parameter conflicts.
- Preserve legacy emotion tags and trusted manual Live2D actions while removing raw motion indices from the LLM output path.
- Add an isolated `live2d-performance` review feature without changing the frozen `text-boundaries` or `sparse` fixtures.

## Capabilities

### New Capabilities

- `semantic-live2d-performance`: Defines the response marker, validated performance plan, audio-aligned delivery, deterministic fallback, and model-scoped semantic profile.

### Modified Capabilities

- `live2d-vue-component`: Changes idle and expression behavior to use deterministic layered performance control with lip-sync parameter ownership.
- `local-livestream-review`: Adds an isolated semantic-expression and accent review feature while preserving the frozen existing catalog.

## Impact

The change affects avatar analysis and prompt construction, LangGraph state and TTS/output delivery, Socket.IO event types, Hiyori model metadata, the Vue Live2D renderer, and local review fixtures/tests. It adds no external dependency, model asset, production fault-injection API, or additional LLM request.

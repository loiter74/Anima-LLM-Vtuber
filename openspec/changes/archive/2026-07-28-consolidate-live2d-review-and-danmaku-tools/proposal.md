## Why

The current Live2D performance and local review implementation repeats the same semantic catalog and compatibility mappings across backend, socket types, renderer profiles, and review tooling. Experimental danmaku collectors also duplicate the production connection lifecycle, making the accepted behavior harder to maintain and extend safely.

## What Changes

- Make `calm`, `annoyed`, and `surprised` the only canonical Live2D performance bases, with `none` as the only canonical accent.
- Keep the previous semantic and emotion labels as deterministic ingress compatibility values while preventing them from leaking into emitted plans.
- Separate the renderer state machine, model-scoped parameter profile, and model adapter while preserving the accepted Hiyori visuals and lip-sync ownership.
- Separate TTS review process lifecycle, authenticated synthesis, evidence acquisition, and feature-specific sample orchestration.
- Extend review evidence with optional named audio samples while retaining the existing single audio/report fields.
- Restore the historical-video `collect_danmaku.py` command and add a separate live-room collector over the production danmaku gateway.
- Remove superseded collector experiments and generated output, align the opt-in skill documentation, and map the affected areas into the quality catalog.

## Capabilities

### New Capabilities

- `live-danmaku-collector`: Defines the bounded CLI, normalized output, lifecycle, and credential handling for reusable live-room danmaku capture.

### Modified Capabilities

- `semantic-live2d-performance`: Narrows the canonical performance vocabulary and formalizes legacy normalization without changing compatible emotion/VAD output.
- `extensible-local-review-pipeline`: Adds backward-compatible named multi-sample audio evidence and separates reusable harness responsibilities.

## Impact

The change affects avatar performance parsing and prompts, Live2D renderer/profile code, Socket.IO types, local review plugins and evidence, Bilibili collector scripts, focused tests, repository ignore rules, and impact-aware quality selection. It does not change production TTS routing, Hiyori parameter values, lip-sync timing, frozen livestream review fixtures, or existing historical-video collector semantics.

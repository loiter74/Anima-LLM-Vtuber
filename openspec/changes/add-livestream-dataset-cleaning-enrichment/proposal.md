## Why

The captured replay datasets contain multilingual chat noise, repeated spam, and messages without actionable intent, so they are poor inputs for evaluating Chinese VTuber interaction quality. Animetta needs a reproducible cleaning and clearly marked enrichment pipeline that preserves real baselines while adding auditable long-tail interaction scenarios.

## What Changes

- Add balanced deterministic and LLM-assisted cleaning for replyable livestream events, including contextual intent classification and Chinese localization.
- Produce an immutable real-only cleaned dataset and a separately marked enriched dataset from every source dataset.
- Calibrate a cleaned high-heat source with deterministic real-only continuous time compression when filtering would otherwise lower its tier.
- Add deterministic medium-heat derivation from cleaned high-heat real events without using synthetic events to qualify the tier.
- Add context-aware synthetic danmaku, gift, and super-chat events with visible and machine-readable provenance.
- Add schema v2 manifests, rolling workload validation, provenance validation, cleaning evidence, and CLI orchestration while retaining v1 read/replay compatibility.

## Capabilities

### New Capabilities
- `livestream-dataset-cleaning`: Defines balanced Chinese cleaning, intent classification, deterministic real-only heat calibration and medium-tier derivation, synthetic scenario enrichment, provenance, and cleaning evidence.

### Modified Capabilities
- `livestream-replay-evaluation`: Extends dataset validation and replay to accept schema v2, separate real and effective workload, and preserve schema v1 compatibility.

## Impact

- Affects `evaluations/livestream/`, its focused tests, and the livestream quality catalog mapping.
- Adds a `clean` CLI command and runtime outputs under `data/livestream_eval/` plus audit evidence under `artifacts/livestream-eval/`.
- Reuses Animetta's strict DeepSeek LLM provider; no API key, original foreign text, room identifier, or raw protocol payload is added to generated outputs.
- Does not change the existing Socket.IO danmaku contract or add a frontend control surface.

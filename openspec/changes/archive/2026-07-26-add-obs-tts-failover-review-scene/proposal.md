## Why

Animetta can now fall back from DashScope to the local Qwen3-TTS runtime, but the OBS review pipeline cannot exercise or audibly review that behavior. A deterministic, isolated review feature is needed to prove billing-triggered failover, retain machine-readable audio evidence, and let an operator judge the approved Chinese voice without changing production services.

## What Changes

- Add an independent `tts-failover` review feature with one `billing-to-local` scene and fixed Chinese copy.
- Add a loopback-only review harness that drives the real `FailoverTTS`, a deterministic DashScope billing stub, and the authenticated 8767 fallback.
- Extend review plugins with optional run/attempt lifecycle hooks and capability requirements.
- Extend version-two attempt evidence with optional audio, backend-report, and structured observation fields while preserving older records.
- Let the OBS adapter monitor Browser Source audio during this feature and restore all prior OBS state afterward.
- Reuse the real livestream page and add a review-only top notification bar that plays the generated WAV and exposes stable status/metric assertions without replacing the broadcast surface.

## Capabilities

### New Capabilities

- `obs-tts-failover-review`: Deterministic billing-to-local synthesis, audible OBS review, performance gates, and safe audio/report evidence.

### Modified Capabilities

- `extensible-local-review-pipeline`: Optional plugin lifecycle hooks, declared runtime capabilities, audio/report artifacts, and reversible OBS audio monitoring.

## Impact

- Affects the local TypeScript review registry, CLI, evidence records, browser/OBS adapters, and a review-only overlay mounted by the existing livestream page.
- Adds a Python review harness under scripts that imports the production TTS provider stack but exposes no production route.
- Requires the existing authenticated Qwen host service on loopback port 8767 for real review; CI contract tests use a fake local fallback.
- Leaves the frozen livestream scene catalog and production Docker topology unchanged.

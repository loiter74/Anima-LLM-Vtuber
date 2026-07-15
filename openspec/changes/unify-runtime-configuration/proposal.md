## Why

Animetta currently selects providers from several YAML files, environment overrides, frontend build variables, and deployment descriptors, so the same apparent launch can resolve different ASR/TTS/LLM/VAD implementations and silently fall back to Mock. A single validated manifest and an explicit remote-model boundary are needed so local validation, Docker, and production start from the same declared configuration and expose the provider they actually run.

## What Changes

- **BREAKING** Replace `config/config.yaml`, `config/config.golden.yaml`, `config/services.yaml`, and provider-selection environment overrides with one `config/animetta.yaml` manifest containing exactly three profiles: `test`, `smoke`, and `production`.
- Require `ANIMETTA_PROFILE` at startup and restrict environment expansion to declared secrets and deployment endpoints; reject legacy `ANIMETTA_LLM`, `ANIMETTA_ASR`, `ANIMETTA_TTS`, `ANIMETTA_VAD`, and `VITE_API_URL` selection paths.
- Resolve the manifest once into an immutable, redacted `EffectiveConfig` with version, provider identity, effective hash, and deployment-independent semantic hash shared by service construction, readiness, observability, route handlers, and the frontend settings view.
- Permit Mock providers only in the explicit `test` profile. Make `smoke` and `production` fail closed on missing configuration, provider construction failures, readiness identity mismatches, or attempted implicit Mock fallback.
- Move Qwen3 Alice synthesis behind a versioned HTTP TTS service contract with liveness, readiness, identity, and speech endpoints. Keep model weights, Torch/CUDA, and Qwen runtime dependencies out of the main Animetta application image.
- Make the browser use same-origin Socket.IO/API routing. Reduce Compose, Fly, Zeabur, and local launchers to profile selection plus endpoint/secret injection instead of duplicating business configuration.
- Add unit, provider-contract, integration, deployment-static, browser, Docker, fault-injection, and ten-minute production regression gates with quantitative latency, identity, log, image-size, and Mock-isolation targets.

## Capabilities

### New Capabilities

- `runtime-config-manifest`: Defines the canonical manifest, profile semantics, environment whitelist, immutable effective configuration, migration rules, frontend visibility, and cross-launch configuration parity.
- `remote-tts-service`: Defines the Qwen3 Alice service boundary, health/readiness/identity/speech API contract, runtime degradation behavior, and main-image/model-image separation.

### Modified Capabilities

- `runtime-config-reload`: Restrict atomic hot reload to persona and explicitly lightweight LLM/UI fields while rejecting profile, provider, model identity, and endpoint changes as restart-required.
- `service-pool`: Construct services only from the shared EffectiveConfig, expose configured and resolved identities, and prohibit implicit Mock fallback in real profiles.
- `component-health-check`: Make readiness validate required remote-provider identity and EffectiveConfig version/hash without turning cheap liveness into a network probe.

## Impact

- Backend configuration models and loaders under `src/animetta/config/`, service factories and pool construction under `src/animetta/services/` and `src/animetta/core/`, runtime reload, readiness/health routes, status/config APIs, and structured diagnostics.
- TTS provider integration plus a new independently deployable Qwen TTS service/image and its API contract tests.
- `config/`, Dockerfiles and Compose files, Fly/Zeabur descriptors, startup/preflight scripts, dependency groups, and deployment documentation.
- Vue Socket.IO bootstrap and settings/status surfaces, Vite proxy configuration, frontend environment declarations, and fresh Playwright regression capture.
- Existing golden-path and slim-image changes remain authoritative for dialogue/media acceptance and dependency layering; this change supplies their single configuration and remote TTS boundary.

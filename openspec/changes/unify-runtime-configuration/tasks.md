## 1. Baseline and Test Harness

- [x] 1.1 Record current configuration/provider selection paths and add a machine-readable legacy-selector fixture covering YAML, environment, frontend, Compose, Fly, and Zeabur inputs
- [x] 1.2 Add shared test helpers for isolated environment variables, temporary manifests, fake remote HTTP services, and configured/resolved provider identity assertions
- [x] 1.3 Add pytest markers/commands for config-unit, provider-contract, real-smoke, production-fault, and production-soak suites without weakening existing default gates

## 2. Canonical Manifest and EffectiveConfig

- [x] 2.1 Write failing `CFG-001`–`CFG-006` tests for exact test/smoke/production resolution, mandatory/unknown profile failures, complete service maps, unknown references, unknown fields, merge/inheritance rejection, and schema version errors
- [x] 2.2 Implement strict Pydantic V2 manifest, profile, policy, provider-reference, and runtime models under `src/animetta/config/`
- [x] 2.3 Write failing `CFG-007`–`CFG-009` tests for field-scoped secret/endpoint expansion, missing required values, forbidden business-field expansion, and legacy selector detection
- [x] 2.4 Implement the field-scoped environment resolver and redacted legacy migration errors with no provider-selection override path
- [x] 2.5 Write failing `CFG-010`–`CFG-012` tests for frozen EffectiveConfig, deterministic effective/semantic hashes, secret/path redaction, and sanitized public status output
- [x] 2.6 Implement one-shot manifest resolution, typed provider configs, immutable EffectiveConfig publication, canonical hashing, and public redaction
- [x] 2.7 Create `config/animetta.yaml` with complete non-inheriting `test`, `smoke`, and `production` service maps and explicit policy/runtime settings
- [x] 2.8 Add a focused branch-coverage command and make the loader, policy, hash/redaction, and legacy detector achieve 100 percent branch coverage in under five seconds

## 3. Bootstrap, ServicePool, and Fail-Closed Providers

- [x] 3.1 Write failing `RUN-001`–`RUN-003` tests proving bootstrap resolves once and ServicePool, route handlers, sessions, traces, and readiness share one EffectiveConfig version/hash
- [x] 3.2 Cut application bootstrap and active-config holders over to the immutable EffectiveConfig without independent `AppConfig.load()` calls
- [x] 3.3 Write failing `RUN-004`–`RUN-006` tests for explicit test Mock construction, real-profile Mock rejection, provider construction/import failure, and configured/resolved mismatch
- [x] 3.4 Pass ProviderPolicy and typed configs into LLM/ASR/TTS/VAD factories, remove application-level implicit Mock fallback, and attach sanitized configured/resolved identities
- [x] 3.5 Update ServicePool status snapshots and observability fields to carry profile, config version/hash, readiness, and separate identities without secrets

## 4. Remote Qwen3 Alice TTS Boundary

- [x] 4.1 Write fake-server `PRV-001`–`PRV-004` and `QTS-001`–`QTS-009` tests for health, readiness, identity, valid WAV/MIME, authentication, timeout, 4xx/5xx, wrong model/voice, empty audio, request correlation, and bounded concurrency
- [x] 4.2 Implement typed remote TTS configuration and async RemoteTTS client with exact identity/readiness and per-response validation
- [x] 4.3 Implement the standalone Starlette Qwen TTS service with `/health`, `/ready`, `/v1/identity`, `/v1/audio/speech`, sanitized errors, preload, Alice prompt initialization, and bounded GPU work
- [x] 4.4 Add typed timeout/auth/remote/identity/audio exceptions and connect them to the existing TTS media-degraded state without empty or fake audio
- [x] 4.5 Write and pass `RUN-007`–`RUN-009` fault tests proving text/Live2D continuity, no provider swap, and same-Qwen retry on the next turn

## 5. Reload, Readiness, Status API, and Frontend

- [x] 5.1 Write failing reload tests for atomic allowlisted persona/lightweight settings, restart-required profile/provider/model/voice/endpoint/auth changes, version/hash publication, and preserved engines
- [x] 5.2 Implement EffectiveConfig diff classification and publish one successful immutable reload snapshot to every active holder
- [x] 5.3 Write failing readiness tests for cheap `/health`, cached `/ready`, missing ServicePool, stale config snapshot, remote identity mismatch, and sanitized structured causes
- [x] 5.4 Implement identity-bearing readiness snapshots and sanitized runtime config/status API responses without provider network work in `/health`
- [x] 5.5 Write frontend unit tests for same-origin Socket.IO, relative APIs, separate ASR/TTS configured/resolved rows, and removal of `VITE_API_URL`
- [x] 5.6 Update `useSocket`, Vite proxy/env typing, and the settings/status surface to consume the sanitized EffectiveConfig view through same-origin routing

## 6. Dependency and Deployment Separation

- [x] 6.1 Add dependency/import regression tests proving the core application can import and run without Torch, CUDA, Qwen TTS, local Whisper/Silero model packages, weights, or reference audio
- [x] 6.2 Split Python dependency groups and Docker build stages into a core Animetta application image and independent Qwen TTS GPU image
- [x] 6.3 Update production Compose to run `production` with internal Qwen health dependency and update CPU Compose to run `smoke` with remote API secrets only
- [x] 6.4 Update Fly, Zeabur, nginx, entrypoint, and local/Vite launch configuration so descriptors inject only profile, endpoints, and secrets
- [x] 6.5 Add image inspection/size evidence that the core image contains no prohibited model dependencies/assets and is at most 2.5 GB uncompressed with a 1–2 GB target

## 7. One-Time Migration and Static Regression Gates

- [x] 7.1 Migrate scripts, tests, documentation, and examples to `config/animetta.yaml` and explicit `ANIMETTA_PROFILE`
- [x] 7.2 Remove `config/config.yaml`, `config/config.golden.yaml`, `config/services.yaml`, legacy `ANIMETTA_CONFIG` and provider-selector readers/references, factory fallback wiring, and `VITE_API_URL`
- [x] 7.3 Implement `DEP-001`–`DEP-011` static gates for legacy files/symbols, descriptor provider selection, same-origin frontend, secret leakage, dependency separation, health dependency wiring, and configuration hash parity
- [x] 7.4 Run repository secret/log/config-API scans and verify no API key, token, secret-derived digest, sensitive local path, Traceback, or ERROR evidence is emitted

## 8. Focused and Full Automated Verification

- [x] 8.1 Run and pass configuration unit/coverage gates with the specified branch coverage and duration targets
- [x] 8.2 Run and pass remote-provider/Qwen fake contract tests within 30 seconds with zero Mock construction
- [x] 8.3 Run and pass ServicePool, runtime reload, readiness, orchestration degradation, and frontend unit/integration suites
- [x] 8.4 Run and pass ruff, mypy for affected modules, frontend typecheck/build, and the repository default non-slow/non-integration pytest suite
- [x] 8.5 Run `openspec validate unify-runtime-configuration --strict` and reconcile every scenario with a test, static gate, or runtime evidence source

## 9. Runtime Acceptance and Evidence

- [x] 9.1 Use a startup sub-agent to execute the full CPU Docker protocol for `smoke`: down, build, detached start, `/health` polling, frontend 200 polling, and zero Traceback/ERROR log scan
- [x] 9.2 Execute real `E2E-S001`–`E2E-S005` DeepSeek/MiMo text/TTS/ASR/VAD and provider-display checks within 120 seconds with zero Mock
- [x] 9.3 Use a startup sub-agent to execute the full GPU production Docker protocol with the independent Qwen service and exact Alice readiness identity
- [x] 9.4 Use the QA and Playwright workflow to acquire a fresh page, complete a Chinese production turn, verify playable Alice audio and provider rows, inject one typed TTS failure, and verify next-turn recovery with no console error
- [x] 9.5 Run the clean production golden soak for at least 600 seconds and 12 turns; verify zero disconnects, Tracebacks, ERROR, Mock, identity mismatch, duplicate reply, and fake audio; enforce text p95 <=8 seconds, media p95 <=20 seconds, and at most one non-consecutive typed TTS degradation
- [x] 9.6 Produce the final requirement-by-requirement audit linking every explicit scenario and quantitative target to current test output, image/config inspection, browser capture, Docker logs, or generated soak evidence

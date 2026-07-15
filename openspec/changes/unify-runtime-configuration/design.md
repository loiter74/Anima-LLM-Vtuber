## Context

The current runtime configuration has four independent selection layers: `config/config*.yaml`, the registry in `config/services.yaml`, `ANIMETTA_{LLM,ASR,TTS,VAD}` overrides, and deployment/frontend variables. Current Compose variants select different files and providers, Fly selects Kokoro directly, Vite can bypass same-origin routing through `VITE_API_URL`, and non-strict factories can replace a failed provider with Mock. This made `localhost` capable of showing a different effective stack from the stack implied by the edited YAML.

The change crosses configuration, service construction, readiness, frontend bootstrap, Docker/deployment descriptors, and the Qwen GPU boundary. It must preserve the existing Pydantic V2 provider models, ProviderRegistry, shared ServicePool lifecycle, atomic persona/lightweight-LLM reload, typed golden-path TTS degradation, and the existing ten-minute acceptance runner. Python 3.13, async I/O, Starlette/Socket.IO, Vue 3, and loguru conventions remain unchanged.

## Goals / Non-Goals

**Goals:**

- Make `config/animetta.yaml` the only runtime business-configuration manifest.
- Provide three explicit, non-inheriting profiles optimized for deterministic tests, quick real-API validation, and production.
- Produce one immutable EffectiveConfig used by every backend consumer and safely exposed to the frontend.
- Prohibit accidental Mock use and configured/resolved provider mismatches outside `test`.
- Move Qwen3 Alice inference into a separately deployable HTTP service and remove its model stack from the application image.
- Make all browser traffic same-origin and limit deployment variables to profile, secrets, and endpoints.
- Define executable regression cases and quantitative release targets for every original failure mode.

**Non-Goals:**

- Replacing the ProviderRegistry or rewriting provider business logic.
- Combining persona documents, tool catalogs, socket event schemas, singing assets, or large voice/model assets into the manifest; the manifest references these resources by path or identity.
- Hot-swapping engines, profiles, provider identities, models, or endpoints in a live process.
- Designing the golden two-pass dialogue pipeline or changing its event contract.
- Providing an automatic voice substitution when Alice is unavailable.

## Decisions

### 1. One manifest with explicit profiles and provider declarations

`config/animetta.yaml` has four top-level domains:

```yaml
schema_version: 1
application:
  persona: anima.v0.1
  system:
    host: ${ANIMETTA_HOST}
    port: ${ANIMETTA_PORT}
  observability: {}

providers:
  llm: {}
  asr: {}
  tts: {}
  vad: {}

profiles:
  test:
    services: {llm: mock, asr: mock, tts: mock, vad: mock}
    policy: {allow_mock: true, require_remote_identity: false}
    runtime: {}
  smoke:
    services: {llm: deepseek, asr: mimo-asr, tts: mimo-tts, vad: mimo-vad}
    policy: {allow_mock: false, require_remote_identity: true}
    runtime: {}
  production:
    services: {llm: deepseek, asr: mimo-asr, tts: qwen-alice, vad: mimo-vad}
    policy: {allow_mock: false, require_remote_identity: true}
    runtime: {}
```

Each profile repeats all four service references; profile inheritance, YAML merge keys, implicit defaults, and partial overlays are rejected. Provider configuration remains declared once under `providers`, using the existing typed provider models where possible. Persona YAML, tools, singing configuration, socket schemas, reference audio, and model weights remain separate resources referenced from the manifest.

This was selected over multiple profile files plus a catalog because a single reviewable document eliminates file-selection ambiguity. A generator was rejected because generated output introduces another source-of-truth question.

### 2. Profile selection is mandatory and environment use is field-scoped

The loader accepts an explicit function argument first and otherwise requires `ANIMETTA_PROFILE`. There is no development default. The only business manifest path is the repository/application-relative `config/animetta.yaml`; `ANIMETTA_CONFIG` is removed.

Environment expansion is allowed only in Pydantic fields classified as:

- `secret`: API keys and authentication tokens;
- `endpoint`: application bind host/port and remote service base URLs.

Provider names, model IDs, voices, behavior flags, timeouts, and persona selection cannot be changed through environment variables. Unresolved required values, expansion in any unclassified field, `${VAR:default}` for a required secret, or the presence of legacy selector variables fails validation with a redacted migration error. `ANIMETTA_PROFILE` selects a complete profile but never mutates one.

This whitelist was selected over arbitrary `${...}` expansion because arbitrary expansion recreates the hidden override layer. Secret managers and orchestrators remain usable without making configuration opaque.

### 3. Resolution produces an immutable EffectiveConfig

The loader performs a deterministic pipeline:

1. parse the manifest with safe YAML loading;
2. validate schema version and reject unknown fields;
3. select the explicit profile;
4. verify all four references and policy invariants;
5. expand only field-scoped endpoint/secret references;
6. instantiate typed provider configs;
7. compute identities and hashes;
8. freeze the result before publishing it.

`EffectiveConfig` is a frozen Pydantic model containing the selected profile, version, resolved application/runtime configuration, typed provider configs, configured provider identities, `effective_hash`, and `semantic_hash`. The effective hash includes deployment endpoints but replaces secret values with their environment variable names. The semantic hash additionally removes endpoint values so local, Docker, and hosted launches of the same profile can prove business-configuration parity.

ServicePool, route handlers, runtime reloader, readiness snapshots, traces, and settings/status APIs receive the same object or versioned snapshot. No consumer calls `AppConfig.load()` independently after bootstrap. The public representation exposes profile, version, hashes, persona, configured/resolved provider type/model/voice, and restart-required fields; it never exposes secret values or sensitive local paths.

### 4. Real profiles are fail-closed from configuration through service resolution

The selected profile supplies a `ProviderPolicy` to every factory. `test` may construct only its explicitly referenced Mock services. `smoke` and `production` reject:

- any configured provider whose declared type is Mock;
- unknown provider references or missing required secrets/endpoints;
- provider import or construction failure;
- a resolved class/type/model/voice that differs from EffectiveConfig;
- any factory attempt to invoke a Mock fallback.

Factories retain their reusable registry behavior, but the fallback branch is removed from application startup. Tests that exercise factory fallback directly are migrated to explicit test-profile behavior. A real provider runtime failure returns its typed error/degradation; it does not mutate ServicePool or the effective identity.

Fail-closed resolution was selected over fallback chains because a successful-looking response from the wrong engine is worse than an actionable readiness failure and was the cause of the reported ambiguity.

### 5. Remote providers use a common readiness identity, with Qwen as the first model service

Remote services expose a small identity document:

```json
{
  "api_version": "1",
  "service": "qwen-tts",
  "provider": "qwen3",
  "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
  "voice": "alice",
  "revision": "<resolved revision>",
  "ready": true
}
```

The Qwen service implements:

- `GET /health`: cheap process liveness with no generation or model load;
- `GET /ready`: cached dependency/model/prompt readiness and exact identity;
- `GET /v1/identity`: the sanitized identity document;
- `POST /v1/audio/speech`: OpenAI-shaped request using `model`, `voice`, `input`, `response_format`, optional `language`, and `request_id`; returns non-empty audio with `Content-Type` and identity/request headers.

The application-side `RemoteTTS` validates identity during readiness and validates response headers for every synthesis. Timeouts, authentication failures, 4xx/5xx responses, malformed identity, model/voice mismatch, empty audio, and unsupported content types become typed exceptions. The Qwen worker preloads its model and Alice prompt before readiness, serializes or bounds GPU work according to capacity, and never downloads model weights during a readiness request.

A Qwen-specific protocol was kept narrow and OpenAI-shaped rather than embedding a general inference platform. This provides a stable boundary now without forcing ASR/LLM rewrites; future local models can implement the same health/identity pattern.

### 6. Qwen failure preserves text and identity instead of swapping voice

In `production`, a runtime Qwen failure returns no audio, emits the existing typed `tts_degraded`/media-degraded state, preserves text and Live2D output, records a sanitized warning and trace category, and retries the same Qwen provider on the next turn. It never emits empty/fake audio and never substitutes MiMo or Mock.

Startup identity mismatch or initial unready state keeps `/ready` unsuccessful. Once running, a transient synthesis failure is a turn-level degradation rather than a process crash. This matches the existing golden-path state machine while making the remote boundary observable.

### 7. Reload is explicitly divided into hot and restart-required fields

Atomic reload may update persona content and an allowlist of lightweight LLM/UI behavior values already supported by active holders. The loader resolves a candidate EffectiveConfig and computes a field-level diff. Changes to profile, provider reference/type, model, voice, endpoint, authentication reference, service policy, or schema version return `ok: false`, `preserved: true`, and `restart_required` fields without modifying the active object or engine identities.

Successful hot reload increments the runtime config version and republishes one immutable snapshot to active route/session holders. Failure preserves the previous config, hashes, version, and engines. This was selected over engine hot swapping because shared GPU/network clients and active sessions cannot be replaced atomically without a much larger lifecycle design.

### 8. Deployment descriptors choose topology, not business providers

The main application image contains the Python core dependency group and built frontend only. It must not install/import Torch, CUDA wheels, `qwen-tts`, local Whisper/Silero model stacks, Qwen weights, or Alice reference audio. A separate `qwen-tts-service` GPU image owns those dependencies and resources.

Deployment topology is:

- local unit/CI: `ANIMETTA_PROFILE=test`, no external services;
- CPU Compose quick validation: `ANIMETTA_PROFILE=smoke`, remote DeepSeek/MiMo;
- GPU/production Compose: `ANIMETTA_PROFILE=production`, application plus `qwen-tts-service` on the internal network;
- Fly/Zeabur/static hosts: select `smoke` or `production` and inject only provider secrets and remote endpoints.

Compose/Fly/Zeabur files cannot contain provider selector names other than the profile itself and endpoint topology. The application waits on dependency readiness through Compose health conditions or preflight and publishes `/ready` only after identity checks. The cheap `/health` endpoint remains process-local.

### 9. The browser is always same-origin

`useSocket` connects to `window.location.origin` and all REST calls remain relative. `VITE_API_URL` is removed from code, env typings, examples, and builds. During development, Vite proxies `/socket.io` and `/api` to the endpoint-only `ANIMETTA_BACKEND_URL` (defaulting to the manifest bind port for the standard local command). Production nginx uses the same paths.

The settings/status surface reads the sanitized runtime configuration endpoint and renders ASR and TTS as separate configured/resolved rows. A mismatch is a readiness error, not a UI warning. This eliminates build-time provider drift while retaining explicit tunnel/proxy support at the routing layer.

### 10. Regression gates are requirement-linked and evidence-producing

Tests use stable IDs so failures map directly to release gates.

| Suite | Required cases | Target |
|---|---|---|
| Configuration unit (`CFG-001`–`CFG-012`) | exact profile resolution; missing/unknown profile; unknown refs; forbidden expansion; legacy selector detection; Mock invariant; frozen model; stable/redacted hashes; sanitized API; restart-only diff | 100% branch coverage for the new manifest loader, policy validator, hash/redaction, and legacy detector; under 5 seconds |
| Provider contract (`PRV-001`–`PRV-004`, `QTS-001`–`QTS-009`) | remote auth/timeout/4xx/5xx; Qwen liveness/readiness/identity/speech; valid WAV/MIME; wrong model/voice; empty audio; request correlation; concurrent capacity | all cases deterministic against fake servers; under 30 seconds; zero Mock construction |
| Runtime integration (`RUN-001`–`RUN-009`) | one EffectiveConfig across pool/handlers/readiness/traces; configured/resolved match; atomic hot reload; restart rejection; typed TTS degradation/retry; no fake audio; semantic parity | all identities and versions equal; no implicit reload or provider replacement |
| Deployment static (`DEP-001`–`DEP-011`) | no legacy files/readers/variables; profile-only descriptors; same-origin frontend; secret scan; dependency/image separation; health dependencies; semantic-hash parity | zero forbidden references/secrets; main image uncompressed size target 1–2 GB and hard gate <=2.5 GB |
| `test` E2E (`E2E-T001`–`T003`) | deterministic startup and turn with network blocked | ready <=10 seconds; zero external calls |
| `smoke` E2E (`E2E-S001`–`S005`) | real DeepSeek/MiMo text, TTS, ASR/VAD confirmation, provider display, failure behavior | suite <=120 seconds; zero Mock; every configured/resolved identity equal |
| `production` E2E (`E2E-P001`–`P009`) | Qwen exact readiness, real Chinese turn, playable Alice audio, fresh browser capture, injected degradation/recovery, log/secret scan, soak | at least 600 seconds/12 turns; zero disconnects, Tracebacks, ERROR, Mock, identity mismatch, duplicate replies, or fake audio; text p95 <=8s; media p95 <=20s; at most one non-consecutive typed TTS degradation |

The original incident receives dedicated regressions: one launch cannot yield different semantic hashes across CLI/Vite/Docker views; ASR and TTS rows cannot be conflated; configured/resolved mismatch fails readiness; and CPU/GPU/hosted descriptors cannot independently select Mock or another provider. Browser tests always capture a fresh page after the tested services start.

## Risks / Trade-offs

- **[Breaking configuration migration]** Existing scripts and personal launch commands will fail until updated → Provide a deterministic legacy scanner with exact replacement guidance, update repository entrypoints in one change, and use source-control rollback rather than dual loaders.
- **[Remote TTS adds network latency and another failure boundary]** → Keep the service on an internal network in Compose, preload before readiness, use bounded timeouts and request IDs, and preserve typed text-only degradation.
- **[MiMo endpoints may not expose a standard identity API]** → Require construction/credential/endpoint validation at readiness and prove actual model behavior in the smoke contract request; never claim an identity that the response cannot substantiate.
- **[Hash parity can be confused by deployment endpoints]** → Publish both effective and semantic hashes with precisely defined exclusion sets and test both canonicalization paths.
- **[Removing local model dependencies can break optional contrib providers]** → Keep them in explicit optional/service image dependency groups; static import tests ensure the core image does not eagerly import them.
- **[Strict startup reduces apparent availability]** → Keep cheap liveness separate from readiness and return structured, redacted causes so operators can correct configuration instead of receiving a false-positive service.
- **[Image-size limits depend on Docker storage reporting]** → Record compressed and uncompressed sizes plus image digest in evidence; enforce the <=2.5 GB uncompressed hard gate on the application image only.

## Migration Plan

1. Add the new schema models, loader, redaction/hash helpers, and failing configuration tests without wiring a second runtime path.
2. Add RemoteTTS plus a fake contract server and Qwen service package/image; prove its contract and typed failures independently.
3. Create `config/animetta.yaml`, cut bootstrap and ServicePool consumers directly to EffectiveConfig, and migrate all backend/frontend tests and scripts in the same commit series.
4. Update runtime reload, readiness/status APIs, traces, and settings UI to use the shared versioned snapshot.
5. Split dependency groups and images; update CPU/GPU Compose, Fly/Zeabur, Vite, nginx, and startup preflight to profile/endpoint/secret-only configuration.
6. Run the legacy scanner, then remove old runtime YAMLs, selector overrides, fallback wiring, and `VITE_API_URL`. There is no long-lived compatibility loader.
7. Run focused unit/contract/integration suites, static deployment gates, complete Docker startup protocol, fresh Playwright capture, failure injection, and the production soak. Store generated evidence only through existing pipelines.
8. Roll back by deploying the previous release/image and manifest together. Do not mix a new binary with old configuration files or re-enable hidden provider overrides.

## Open Questions

No product decisions remain open. Deployment-specific Qwen model revision, service credentials, and externally hosted endpoint values are supplied at release time and recorded in sanitized readiness/evidence rather than hard-coded into business profiles.

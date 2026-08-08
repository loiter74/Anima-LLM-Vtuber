# runtime-config-manifest Specification

## Purpose
TBD - created by archiving change unify-runtime-configuration. Update Purpose after archive.
## Requirements
### Requirement: One manifest is the runtime configuration source of truth
The system SHALL load runtime business configuration only from `config/animetta.yaml`, SHALL reject unknown schema versions and unknown fields, and SHALL keep referenced personas, tools, event schemas, singing assets, voice assets, and model weights outside the manifest.

#### Scenario: Standard runtime bootstrap
- **WHEN** an Animetta process starts with a valid `config/animetta.yaml` and an explicit profile
- **THEN** it SHALL resolve application, provider, policy, and runtime settings from that manifest
- **AND** no second runtime YAML or provider-selection environment variable SHALL alter the result

#### Scenario: Legacy runtime source remains
- **WHEN** a repository or packaged runtime still contains a loader/reference for `config/config.yaml`, `config/config.golden.yaml`, or `config/services.yaml`
- **THEN** the configuration migration gate SHALL fail with the offending path or symbol

#### Scenario: Unsupported manifest structure
- **WHEN** the manifest has an unsupported `schema_version`, an unknown top-level field, profile inheritance, a YAML merge key, or a partial service map
- **THEN** bootstrap SHALL fail before service construction with a redacted validation error

### Requirement: Profile selection is explicit and complete
The system SHALL require an explicit profile argument or `ANIMETTA_PROFILE`, SHALL define exactly `test`, `smoke`, and `production`, and each profile SHALL explicitly reference one LLM, ASR, TTS, and VAD declaration without inheritance or implicit provider defaults.

#### Scenario: Profile is missing or unknown
- **WHEN** neither an explicit profile nor `ANIMETTA_PROFILE` identifies one of the three declared profiles
- **THEN** bootstrap SHALL fail before binding the application port
- **AND** the error SHALL list the valid profile names without exposing secrets

#### Scenario: Test profile resolves
- **WHEN** `test` is selected
- **THEN** LLM, ASR, TTS, and VAD SHALL resolve to explicitly declared Mock providers
- **AND** the policy SHALL allow Mock and SHALL require no external network request

#### Scenario: Smoke profile resolves
- **WHEN** `smoke` is selected
- **THEN** LLM SHALL resolve to DeepSeek and ASR, TTS, and VAD SHALL resolve to their declared MiMo providers
- **AND** the policy SHALL forbid Mock and require real-provider validation

#### Scenario: Production profile resolves
- **WHEN** `production` is selected
- **THEN** LLM SHALL resolve to DeepSeek, ASR and VAD SHALL resolve to MiMo, and TTS SHALL resolve to the remote Qwen3 Alice provider
- **AND** the policy SHALL forbid Mock and require exact remote TTS identity

#### Scenario: Incomplete profile
- **WHEN** a profile omits any of `llm`, `asr`, `tts`, or `vad`, or references an unknown declaration
- **THEN** manifest validation SHALL fail without substituting a default

### Requirement: Environment expansion is field-scoped
The system SHALL expand environment references only in fields typed as secrets or deployment endpoints. Provider names, types, model IDs, voices, persona names, behavior flags, and timeouts SHALL be literal manifest values.

#### Scenario: Required secret and endpoint are supplied
- **WHEN** every selected provider's declared secret and endpoint environment reference is present
- **THEN** the loader SHALL resolve those values into the private EffectiveConfig representation
- **AND** public configuration, logs, errors, and hashes SHALL not contain the secret values

#### Scenario: Expansion appears in a business field
- **WHEN** an environment expression appears in a provider name, model, voice, persona, behavior flag, or timeout
- **THEN** validation SHALL fail and identify the forbidden field

#### Scenario: Legacy selector is present
- **WHEN** any of `ANIMETTA_CONFIG`, `ANIMETTA_LLM`, `ANIMETTA_ASR`, `ANIMETTA_TTS`, `ANIMETTA_VAD`, `ANIMETTA_LOCAL_LLM`, or `VITE_API_URL` is present or referenced by a repository launch path
- **THEN** the legacy migration gate SHALL fail with a replacement instruction
- **AND** the variable SHALL not override EffectiveConfig

### Requirement: Resolution publishes one immutable EffectiveConfig
The system SHALL resolve the selected manifest exactly once during bootstrap into a frozen EffectiveConfig that is shared by service construction, ServicePool, route handlers, readiness, runtime reload, traces, and the sanitized frontend configuration API.

#### Scenario: Consumers inspect active configuration
- **WHEN** two backend consumers read the active runtime configuration
- **THEN** they SHALL observe the same profile, version, provider identities, effective hash, and semantic hash
- **AND** they SHALL not independently reload configuration from disk

#### Scenario: Consumer attempts mutation
- **WHEN** code attempts to modify a frozen EffectiveConfig field
- **THEN** the operation SHALL fail and the published version and hashes SHALL remain unchanged

#### Scenario: Effective and semantic hashes are computed
- **WHEN** two manifests have the same business configuration but different secret values and deployment endpoints
- **THEN** their semantic hashes SHALL match
- **AND** their effective hashes SHALL differ only when non-secret effective endpoint configuration differs
- **AND** neither hash input nor output SHALL reveal a secret value

#### Scenario: Public configuration is requested
- **WHEN** an authenticated or local caller requests the runtime configuration/status representation
- **THEN** it SHALL include schema/profile/version, persona, hashes, and separate configured/resolved type/model/voice identities for LLM, ASR, TTS, and VAD
- **AND** it SHALL exclude secret values, secret-derived digests, sensitive local paths, and unredacted exception text

### Requirement: Real profiles prohibit Mock across the complete lifecycle
The system SHALL allow Mock providers only when the selected `test` profile explicitly references them. `smoke` and `production` SHALL fail closed on configured Mock, import/construction failure, resolved identity mismatch, or an attempted Mock fallback.

#### Scenario: Real profile declares Mock
- **WHEN** `smoke` or `production` resolves any provider declaration whose type is Mock
- **THEN** configuration validation SHALL fail before service construction

#### Scenario: Real provider cannot be constructed
- **WHEN** a selected real provider is unavailable, invalid, or raises during construction
- **THEN** bootstrap/readiness SHALL report the typed provider failure
- **AND** no Mock object SHALL be instantiated as a substitute

#### Scenario: Configured and resolved identities differ
- **WHEN** ServicePool or a remote readiness response reports a provider type, model, or required voice different from EffectiveConfig
- **THEN** application readiness SHALL fail with a sanitized identity-mismatch reason
- **AND** the settings API SHALL not present the mismatch as healthy

### Requirement: Browser and deployment entrypoints preserve configuration parity
Browser code SHALL use same-origin API and Socket.IO paths, while local launchers and deployment descriptors SHALL select only a profile and inject allowed endpoints/secrets. They SHALL not independently select business providers.

#### Scenario: Browser establishes a connection
- **WHEN** the Vue application starts in Vite or a packaged deployment
- **THEN** Socket.IO SHALL connect through `window.location.origin`
- **AND** REST requests SHALL use relative same-origin paths
- **AND** no build-time API URL SHALL select another backend

#### Scenario: Settings display provider status
- **WHEN** the frontend receives the sanitized runtime configuration
- **THEN** it SHALL display ASR and TTS as separate rows
- **AND** each row SHALL distinguish configured and resolved identities

#### Scenario: Same profile runs in different topologies
- **WHEN** CLI, Vite-proxied, Docker, or hosted launches select the same manifest profile
- **THEN** their semantic hashes SHALL match
- **AND** any effective-hash difference SHALL be explainable only by allowed deployment endpoints

#### Scenario: Deployment descriptor selects a provider
- **WHEN** a Compose, Fly, Zeabur, frontend env, or startup descriptor contains a direct LLM/ASR/TTS/VAD selection
- **THEN** the deployment static gate SHALL fail

### Requirement: Configuration regression gates are release-blocking
The project SHALL maintain deterministic unit, integration, static, browser, and real-profile tests that prove manifest exclusivity, profile semantics, Mock isolation, identity consistency, redaction, and parity.

#### Scenario: Critical configuration suite runs
- **WHEN** the configuration release suite executes
- **THEN** the manifest loader, profile policy, hash/redaction, and legacy detector SHALL achieve 100 percent branch coverage
- **AND** the deterministic configuration suite SHALL finish within five seconds on the supported CI runner

#### Scenario: Test profile E2E runs with network blocked
- **WHEN** `test` starts in a network-denied test environment
- **THEN** readiness SHALL succeed within ten seconds
- **AND** a deterministic conversation SHALL complete without an external request

#### Scenario: Smoke profile gate runs
- **WHEN** valid DeepSeek and MiMo credentials are supplied to the real smoke suite
- **THEN** text, TTS, ASR/VAD confirmation, and configured/resolved identity checks SHALL finish within 120 seconds
- **AND** Mock use SHALL be zero


## ADDED Requirements

### Requirement: Qwen TTS service exposes versioned liveness and identity contracts
The independently deployable Qwen TTS service SHALL expose cheap liveness, cached readiness, and sanitized identity endpoints without performing generation or downloading model assets during those requests.

#### Scenario: Liveness is requested
- **WHEN** `GET /health` is called while the service process can serve requests
- **THEN** it SHALL return HTTP 200 with `status: ok` and service identity
- **AND** it SHALL not load the model, build an Alice prompt, or synthesize audio

#### Scenario: Service is fully ready
- **WHEN** the Qwen model, exact revision, Alice prompt, and required device are loaded
- **THEN** `GET /ready` SHALL return HTTP 200 with `ready: true`, API version, provider, model, revision, voice, and sample rate
- **AND** `GET /v1/identity` SHALL return the same sanitized identity

#### Scenario: Dependency is not ready
- **WHEN** the model, reference prompt, required GPU/device, or other required dependency is unavailable
- **THEN** `/ready` SHALL return a non-success readiness status with a sanitized reason
- **AND** `/health` MAY remain successful as process liveness

### Requirement: Qwen TTS service implements the speech contract
The service SHALL implement `POST /v1/audio/speech` with a versioned OpenAI-shaped request containing `model`, `voice`, `input`, `response_format`, optional `language`, and optional `request_id`.

#### Scenario: Alice synthesis succeeds
- **WHEN** a valid request names the ready model and `alice` voice with non-empty input
- **THEN** the endpoint SHALL return HTTP 200, a supported audio content type, non-empty decodable audio, and headers identifying provider, model, voice, and request ID

#### Scenario: Request identity is unsupported
- **WHEN** the request names a model, voice, language, or response format not supported by the ready service
- **THEN** the endpoint SHALL reject it with a typed 4xx response
- **AND** it SHALL not silently use another model or voice

#### Scenario: Synthesis fails
- **WHEN** generation times out, raises, or produces empty/invalid audio
- **THEN** the endpoint SHALL return a typed failure with the request ID and a sanitized category
- **AND** it SHALL not return empty or fabricated audio as success

#### Scenario: Concurrent requests exceed capacity
- **WHEN** concurrent synthesis demand exceeds the configured GPU capacity
- **THEN** the service SHALL bound or serialize work and return an explicit busy/timeout failure when capacity cannot be met
- **AND** request identities SHALL not be mixed between responses

### Requirement: Animetta validates remote TTS identity and responses
The application-side remote TTS provider SHALL verify readiness identity before declaring application readiness and SHALL validate speech response identity, content type, and non-empty audio on every request.

#### Scenario: Expected identity is ready
- **WHEN** EffectiveConfig expects Qwen3, the configured model, and Alice and the remote identity matches exactly
- **THEN** the TTS provider SHALL publish matching configured and resolved identities
- **AND** application readiness MAY become successful when other dependencies are ready

#### Scenario: Remote identity differs
- **WHEN** provider, model, or voice in remote readiness differs from EffectiveConfig
- **THEN** application readiness SHALL fail with a typed identity mismatch
- **AND** no synthesis request SHALL be treated as healthy

#### Scenario: Remote call fails or is malformed
- **WHEN** authentication fails, the request times out, the service returns 4xx/5xx, identity headers mismatch, content type is unsupported, or audio is empty
- **THEN** RemoteTTS SHALL raise a typed sanitized error
- **AND** it SHALL not construct or call a local/Mock TTS substitute

### Requirement: Runtime TTS failures degrade media without changing voice
After production readiness succeeds, a transient remote Qwen synthesis failure SHALL preserve final text and Live2D delivery, return no audio, emit the typed TTS/media-degraded state, and retry the same configured Qwen provider on the next turn.

#### Scenario: Production synthesis times out
- **WHEN** a ready production turn's Qwen request exceeds its timeout
- **THEN** the turn SHALL keep the authored text and Live2D expression/action
- **AND** it SHALL emit no audio event containing empty or fake audio
- **AND** it SHALL record a sanitized warning/degradation trace with a retryable category

#### Scenario: Next turn follows a degradation
- **WHEN** a turn after a transient Qwen degradation requests speech
- **THEN** it SHALL call the same Qwen model and Alice voice again
- **AND** it SHALL not automatically use MiMo, Mock, or another voice

### Requirement: Application and Qwen model images are isolated
The main Animetta application image SHALL contain only core application/runtime dependencies and SHALL not contain or eagerly import Torch, CUDA runtime packages, Qwen TTS packages, Qwen weights, or Alice reference audio. The independent Qwen image SHALL own those model dependencies and assets.

#### Scenario: Main image is inspected
- **WHEN** the deployment image regression gate examines installed packages, files, and import paths
- **THEN** prohibited Qwen/local-model dependencies and assets SHALL be absent
- **AND** the uncompressed image size SHALL be no more than 2.5 GB, with a target range of 1 to 2 GB

#### Scenario: Production Compose starts
- **WHEN** the production topology is launched
- **THEN** the main application SHALL reach the Qwen service through its internal endpoint
- **AND** application readiness SHALL depend on the Qwen service's exact identity readiness
- **AND** only the Qwen service SHALL require the GPU/model asset mounts

### Requirement: Remote TTS regression gates prove contract and recovery
The project SHALL maintain fake-server contract tests, a production fault-injection rehearsal, and clean production acceptance evidence for the remote TTS boundary.

#### Scenario: Fake contract suite runs
- **WHEN** the deterministic remote TTS contract suite executes
- **THEN** it SHALL cover liveness, readiness, identity, valid audio, authentication, timeout, 4xx, 5xx, wrong model, wrong voice, empty audio, request correlation, and capacity behavior
- **AND** it SHALL finish within 30 seconds with zero Mock construction

#### Scenario: Clean production soak runs
- **WHEN** the release production soak executes
- **THEN** it SHALL run for at least 600 seconds and complete at least 12 turns
- **AND** it SHALL have zero disconnects, Tracebacks, ERROR logs, Mock use, identity mismatches, duplicate authored replies, and fake audio
- **AND** text-ready p95 SHALL be at most 8 seconds and media-ready p95 at most 20 seconds
- **AND** TTS degradation SHALL be zero preferred and at most one non-consecutive typed degradation

#### Scenario: Browser acceptance runs
- **WHEN** the tested production services are freshly started
- **THEN** Playwright SHALL acquire a new page capture, complete a Chinese turn, verify playable Alice audio and separate provider rows, and report no browser console error

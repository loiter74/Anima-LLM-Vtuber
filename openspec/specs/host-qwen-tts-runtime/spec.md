# host-qwen-tts-runtime Specification
## Purpose
TBD - created by archiving change add-dashscope-local-tts-failover. Update Purpose after archive.
## Requirements
### Requirement: Host service exposes authenticated exact identity
The Windows-host Qwen service SHALL expose unauthenticated liveness and authenticated readiness/identity endpoints and SHALL validate requests with a bearer token.

#### Scenario: Correct identity is ready
- **WHEN** the pinned runtime, model files, quantization, voice reference, and sample rate match configuration
- **THEN** authenticated `/ready` SHALL return HTTP 200 with the exact public identity

#### Scenario: Authentication fails
- **WHEN** a protected endpoint receives a missing or incorrect token
- **THEN** it SHALL return HTTP 401 without revealing the expected token

### Requirement: Host service streams PCM16
The speech endpoint SHALL support chunked 24 kHz mono signed 16-bit little-endian PCM without waiting for the full utterance.

#### Scenario: Streaming synthesis
- **WHEN** a valid request sets `stream=true`
- **THEN** the response SHALL emit non-empty even-length PCM chunks in decode order
- **AND** the warm first chunk SHALL arrive within 0.75 seconds on the approved RTX 5090 host

#### Scenario: Non-streaming synthesis
- **WHEN** a valid request sets `stream=false`
- **THEN** the response SHALL contain a valid 24 kHz mono WAV

### Requirement: Host inference is bounded and cancellation-safe
The host service SHALL run one inference worker with at most two queued requests and SHALL not reuse mutable voice state concurrently.

#### Scenario: Queue is full
- **WHEN** one request is running and two requests are queued
- **THEN** an additional request SHALL receive a sanitized busy response

#### Scenario: Client disconnects
- **WHEN** a queued client disconnects
- **THEN** its queued job SHALL be cancelled
- **AND** a running native job SHALL retain capacity until safe termination

### Requirement: Host lifecycle is independently persistent
Lifecycle commands SHALL start, inspect, and explicitly stop the host service while normal Animetta shutdown preserves it.

#### Scenario: Repeated host start
- **WHEN** `host-tts-up` is invoked while the exact service process is ready
- **THEN** it SHALL reuse the process without loading another model

#### Scenario: Animetta stops
- **WHEN** `anima-down` is invoked
- **THEN** the host TTS process SHALL remain running
- **AND** no Qwen Docker image, Compose project, or container lifecycle SHALL exist

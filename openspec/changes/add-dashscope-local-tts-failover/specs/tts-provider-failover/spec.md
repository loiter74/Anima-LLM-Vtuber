## ADDED Requirements

### Requirement: Composite TTS prefers the cloud backend
The system SHALL send each new utterance to the configured primary TTS while its circuit is closed and SHALL report the backend that actually produced the utterance.

#### Scenario: Primary completes normally
- **WHEN** the primary emits valid audio and completes
- **THEN** all audio for that utterance SHALL come from the primary
- **AND** the resolved utterance metadata SHALL identify the primary backend

### Requirement: Failover occurs only before first audio
The system SHALL retry or switch to the fallback only before the first non-empty audio chunk is emitted.

#### Scenario: Primary fails before first chunk
- **WHEN** the primary raises an allowed provider failure before emitting audio
- **THEN** the system SHALL synthesize the same utterance through the fallback

#### Scenario: Primary fails after first chunk
- **WHEN** the primary fails after emitting a non-empty audio chunk
- **THEN** the system SHALL terminate that utterance without appending fallback audio
- **AND** the next utterance SHALL be eligible to use the fallback

### Requirement: Provider failures use bounded retry and circuit breaking
The system SHALL immediately open the circuit for billing or authentication errors, SHALL retry other allowed provider failures once before fallback, and SHALL use a configurable 300-second default cooldown.

#### Scenario: Billing failure
- **WHEN** DashScope reports a non-retryable billing failure
- **THEN** the current utterance SHALL use the fallback without a second cloud attempt
- **AND** the primary circuit SHALL open

#### Scenario: Retryable connection failure
- **WHEN** DashScope fails with a retryable connection error before audio
- **THEN** the system SHALL make one additional primary attempt before using the fallback

### Requirement: Half-open recovery is single-flight
The system SHALL allow only one request to probe the primary after cooldown while concurrent requests continue through the fallback.

#### Scenario: Primary recovers
- **WHEN** the half-open probe completes an utterance successfully
- **THEN** the circuit SHALL close and later utterances SHALL prefer the primary

#### Scenario: Primary remains unavailable
- **WHEN** the half-open probe fails
- **THEN** the circuit SHALL reopen for the full cooldown

### Requirement: Composite preload tolerates one unavailable child
The composite preload SHALL succeed when at least one child backend is ready and SHALL fail when neither child is ready.

#### Scenario: Fallback-only startup
- **WHEN** DashScope preload fails but local Qwen preload succeeds
- **THEN** the composite TTS SHALL become operational in degraded mode

#### Scenario: Both backends fail startup
- **WHEN** both child preloads fail
- **THEN** composite preload SHALL fail with a sanitized aggregate error

## ADDED Requirements

### Requirement: Privacy mode is selected before persistence
The system SHALL apply one ObservationContentPolicy before creating persistence commands. Development SHALL default to `full`; golden and production SHALL default to `redacted` unless an explicit approved override is configured.

#### Scenario: Development trace is stored
- **WHEN** development full mode records a user and assistant turn
- **THEN** the ledger MAY store bounded visible user and final assistant text

#### Scenario: Golden trace is stored
- **WHEN** a golden turn is recorded with default configuration
- **THEN** raw user text, raw assistant text, prompts, and intermediate model objects SHALL NOT appear in any observation table

### Requirement: Redacted content uses bounded facts
Redacted mode SHALL persist only content length, byte length, language, an installation-salted SHA-256 digest, and explicitly allowlisted operational metadata.

#### Scenario: Redacted content is queried
- **WHEN** a production trace detail is returned
- **THEN** it SHALL expose length and digest facts but no reversible content or installation salt

### Requirement: Sensitive payloads are never persisted
The observation system SHALL never persist API keys, authorization headers, secrets, unrestricted prompts, chain-of-thought, audio bytes, base64 media, or complete Socket.IO payloads in any privacy mode.

#### Scenario: Audio event is delivered
- **WHEN** `chat:audio_with_expression` is emitted
- **THEN** the event record SHALL contain event name, payload byte size, phase, status, and identity validity only
- **AND** it SHALL NOT contain audio data or volume arrays

### Requirement: Error persistence is sanitized
Persisted failures SHALL use bounded structured error codes and sanitized summaries. Raw exception representations SHALL NOT be persisted when they may contain request content, credentials, or provider payloads.

#### Scenario: Provider exception contains a secret
- **WHEN** a provider exception message includes an authorization token
- **THEN** the operation SHALL store its classified error code and a redacted summary without the token

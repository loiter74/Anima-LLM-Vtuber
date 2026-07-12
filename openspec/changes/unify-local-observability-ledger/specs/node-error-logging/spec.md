## MODIFIED Requirements

### Requirement: Graph nodes report structured errors to StatsStore
Graph nodes and observed services SHALL report structured failures through the active ObservationRecorder. The recorder SHALL associate the error with the current trace and operation automatically; callers SHALL NOT import the ledger implementation or provide an optional trace ID.

#### Scenario: LLM timeout is reported
- **WHEN** the active reasoner service operation times out
- **THEN** that operation SHALL finish with status `error`, error type `timeout`, allowlisted provider/model identity, and measured duration
- **AND** it SHALL remain a child of the active reasoner workflow operation

#### Scenario: TTS degradation is reported
- **WHEN** TTS returns an allowed retryable provider failure after text delivery
- **THEN** its service operation SHALL finish as `degraded`
- **AND** the trace outcome reducer SHALL be able to select `degraded` rather than `failed`

#### Scenario: No observation context is active
- **WHEN** the compatibility error facade is called outside an observation context
- **THEN** no unlinked operation SHALL be inserted
- **AND** a sanitized warning SHALL be logged and an internal recorder health counter SHALL increment

### Requirement: Error types are classified consistently
The observation domain SHALL recognize at least `timeout`, `rate_limit`, `network_error`, `invalid_response`, `service_unavailable`, `delivery_error`, `cancelled`, and `unknown`. Unrecognized values SHALL be normalized to `unknown` before persistence or metrics labeling.

#### Scenario: Known error is recorded
- **WHEN** a provider reports a network error
- **THEN** the operation error type SHALL be `network_error`

#### Scenario: Unknown error is recorded
- **WHEN** a caller supplies an unrecognized error type
- **THEN** the operation error type SHALL be `unknown`

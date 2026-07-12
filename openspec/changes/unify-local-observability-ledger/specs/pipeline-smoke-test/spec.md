## MODIFIED Requirements

### Requirement: Smoke test uses real Socket.IO client
The smoke test SHALL use a real Socket.IO client against the running server. It SHALL execute a filtered negative probe followed by one normal identity-correlated conversation using the active runtime profile.

#### Scenario: Negative probe is contained
- **WHEN** the client sends a marked `[inspection]` probe
- **THEN** no conversation trace, provider operation, delivery event, session-window mutation, or memory write SHALL be created for that probe

#### Scenario: Real turn executes
- **WHEN** the same client sends a normal acceptance turn with a fresh identity triple
- **THEN** it SHALL receive the profile-required delivery events and resolve `task_id` to one local ledger trace

### Requirement: Event collection via wildcard listener
The smoke test SHALL collect all Socket.IO events with timestamps and identities, then compare them with committed delivery-event evidence for the same task. Extra diagnostic events MAY be retained but SHALL NOT substitute for required events.

#### Scenario: Events and ledger agree
- **WHEN** the real turn reaches terminal control
- **THEN** every required observed client event SHALL have a matching successful ledger delivery event
- **AND** every required ledger delivery event SHALL carry the input identity

#### Scenario: Required event is missing
- **WHEN** terminal control arrives without required text or performance evidence
- **THEN** the smoke test SHALL fail with client-received, ledger-recorded, and missing event sets

### Requirement: Test message isolation
The negative probe and real acceptance turn SHALL be distinguishable. The negative probe SHALL create no trace. The real turn SHALL create operational evidence but SHALL not create forbidden long-term character memory.

#### Scenario: Acceptance trace is inspected
- **WHEN** the real acceptance turn completes
- **THEN** inspection SHALL find its trace by task ID
- **AND** it SHALL verify no prohibited memory ingestion or character-memory operation occurred

### Requirement: Smoke test timeout and resource cleanup
Connection, negative-observation, real-turn, ledger-flush, and post-turn-memory checks SHALL each have bounded timeouts. The client SHALL disconnect and collected evidence SHALL be preserved on success, failure, timeout, or cancellation.

#### Scenario: Ledger evidence does not flush
- **WHEN** terminal control is received but the trace is not queryable before the ledger timeout
- **THEN** the smoke test SHALL fail as observation-incomplete and disconnect cleanly

### Requirement: Smoke test validates actual profile topology and providers
The smoke test SHALL compare committed workflow and service operations against the active profile. Golden mode SHALL prove exactly two real LLM service calls and real TTS audio or an explicit typed degradation; standard and voice modes SHALL validate their own executed topology without a fixed legacy seven-node assumption.

#### Scenario: Golden topology is valid
- **WHEN** a golden acceptance turn succeeds
- **THEN** the trace SHALL include the golden workflow node sequence
- **AND** exactly two non-mock LLM service operations SHALL be recorded
- **AND** TTS SHALL be ready or explicitly degraded

#### Scenario: Mock provider appears in golden mode
- **WHEN** a golden trace records MockLLM or MockTTS as active provider
- **THEN** the smoke test SHALL fail

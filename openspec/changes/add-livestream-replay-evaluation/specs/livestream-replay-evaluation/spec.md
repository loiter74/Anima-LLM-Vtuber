## ADDED Requirements

### Requirement: Privacy-safe normalized capture
The system SHALL normalize supported Bilibili livestream commands into versioned `LivestreamEvent` records and SHALL sanitize each record before it is written to persistent storage.

#### Scenario: Capture a replyable message
- **WHEN** a decoded danmaku, gift, or super-chat command is received
- **THEN** the collector writes a corresponding event with relative time, dataset-local actor alias, sanitized text, and a whitelisted payload
- **AND** it writes no room ID, source UID, source nickname, credential, absolute capture time, or raw command payload

#### Scenario: Capture an engagement signal
- **WHEN** an entry, follow, like update, popularity update, or connection-state command is received
- **THEN** the collector writes the matching non-replyable event type and its whitelisted aggregate fields

#### Scenario: Capture an unknown command
- **WHEN** a command has no supported semantic mapping
- **THEN** the collector records only the sanitized command name and increments the unknown count
- **AND** it does not persist the raw payload

### Requirement: Validated livestream dataset
The system SHALL store each dataset as a JSON manifest and JSONL event stream with a schema version, ordered relative offsets, event counts, workload statistics, sanitizer version, and SHA-256 checksum.

#### Scenario: Validate a complete dataset
- **WHEN** the manifest schema is supported, event offsets are monotonic, counts match, text passes privacy checks, and the checksum is correct
- **THEN** validation succeeds and returns the calculated workload statistics

#### Scenario: Reject an unsafe or corrupt dataset
- **WHEN** a dataset contains an unsupported schema, non-monotonic time, mismatched counts, a checksum mismatch, or residual high-risk identifying text
- **THEN** validation fails with a machine-readable reason before replay begins

### Requirement: Gateway-level deterministic replay
The system SHALL provide a replay Gateway that emits validated events according to relative time, a base speed, and ordered burst windows while following the production Gateway lifecycle.

#### Scenario: Replay at fixed speed
- **WHEN** a valid dataset is started at 10× speed with no burst windows
- **THEN** each input event is emitted once in sequence at its calculated monotonic target time

#### Scenario: Replay high-heat bursts
- **WHEN** the high-heat profile is selected
- **THEN** the scheduler applies 2× for 60 seconds at minute 30, 3× for 30 seconds at minute 60, and 2× for 120 seconds at minute 80
- **AND** it continues consuming the same source-room timeline without cross-room composition

#### Scenario: Stop replay
- **WHEN** stop is called during or after replay
- **THEN** stop is idempotent, no later callback is emitted, and the replay thread exits within five seconds

### Requirement: Reply-path isolation
The system SHALL send only danmaku, gift, and super-chat events through the existing raw-message and AI reply admission path.

#### Scenario: Engagement event is not replied to
- **WHEN** an entry, follow, like, popularity, connection, or unknown event is replayed
- **THEN** event metrics are updated
- **AND** no `DanmakuMessage` is submitted for AI admission

#### Scenario: Existing message payload remains compatible
- **WHEN** a replyable event is handled
- **THEN** the existing Socket.IO danmaku payload and `DanmakuMessage` core fields remain unchanged

### Requirement: Workload qualification
The system SHALL classify datasets using replyable-message counts in rolling 60-second windows and SHALL require at least 80 percent of observed windows to fall inside the selected heat tier.

#### Scenario: Classify heat tiers
- **WHEN** a dataset is validated
- **THEN** low heat is 1–10, medium heat is 11–60, and high heat is 61–300 replyable messages per minute

#### Scenario: Reject an unrepresentative source
- **WHEN** fewer than 80 percent of the observed windows fall inside the selected tier
- **THEN** workload qualification fails and the source cannot become a canonical dataset

### Requirement: Evaluation CLI and evidence
The system SHALL expose `capture`, `validate`, `replay`, and `report` commands and SHALL write generated evidence outside the source tree's tracked fixtures.

#### Scenario: Run a transport evaluation
- **WHEN** an operator replays a dataset in transport mode
- **THEN** the runner uses a deterministic stub reply processor and records event reconciliation, scheduling lag, queue, lifecycle, and resource metrics

#### Scenario: Generate a report
- **WHEN** a replay result and optional completed scoring worksheet are provided
- **THEN** the reporter writes JSON and Markdown summaries, a complete sanitized conversation JSONL file, and a deterministic manual-scoring CSV
- **AND** it creates an explicit post-run safety assessment form plus a non-authoritative hash-only automated content audit
- **AND** a completed post-run safety assessment can update derived report gates without mutating the original replay evidence

### Requirement: Stability and quality gates
The evaluator SHALL calculate the approved automatic gates and manual quality recommendation from recorded evidence.

#### Scenario: Evaluate automatic gates
- **WHEN** a run completes
- **THEN** the result reports event reconciliation, scheduling-lag percentiles, shutdown time, display rate, reply-failure rate, peak queue depth, queue recovery, unhandled failures, and RSS growth against their configured limits

#### Scenario: Produce the manual sample
- **WHEN** a canonical full-stack run contains sufficient replies
- **THEN** a fixed seed selects 5 gift/super-chat, 15 question, and 10 ordinary replies
- **AND** shortages are redistributed deterministically to produce up to 30 rows

#### Scenario: Recommend livestream readiness
- **WHEN** exactly 30 completed scores have an overall mean of at least 4.0, every dimension mean is at least 3.5, the explicit safety assessment records zero severe issues, privacy leaks, and misattributions, and all automatic gates pass
- **THEN** the report marks the quality recommendation as ready

#### Scenario: Keep unreviewed evidence pending
- **WHEN** the scoring worksheet is incomplete or the explicit post-run safety assessment remains unassessed
- **THEN** the report marks baseline readiness as pending
- **AND** advisory pattern scans cannot change that result to passed

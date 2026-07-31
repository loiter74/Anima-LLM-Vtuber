## ADDED Requirements

### Requirement: Anonymous Twitch VOD capture
The system SHALL be able to capture public Twitch VOD chat without authentication and SHALL sanitize selected events before persistence.

#### Scenario: Capture a public VOD window
- **WHEN** an operator supplies a transient VOD identifier, a non-negative start offset, and a formal duration of at least 120 minutes
- **THEN** the collector retrieves fixed time pages, refines dense pages, deduplicates comments, and writes a dataset-relative ordered event timeline
- **AND** no VOD identifier, source URL, commenter login or ID, comment ID, absolute timestamp, or raw GraphQL payload is persisted

#### Scenario: Shape an over-dense source deterministically
- **WHEN** deterministic real-only prefiltering and a replyable rate cap are configured
- **THEN** the collector preserves selected source order and source-relative timing while enforcing the exact rolling 60-second cap
- **AND** the manifest records observed, eligible, and selected counts plus non-identifying derivation settings
- **AND** no synthetic event is used to qualify the captured workload

## MODIFIED Requirements

### Requirement: Validated livestream dataset
The system SHALL store each dataset as a JSON manifest and JSONL event stream with a supported schema version, ordered relative offsets, event counts, workload statistics, sanitizer version, and SHA-256 checksum. Schema v2 datasets SHALL additionally record parent provenance, processing metadata, variant, and effective workload while schema v1 remains readable.

#### Scenario: Validate a schema v1 dataset
- **WHEN** an existing schema v1 manifest and event stream satisfy their original timeline, privacy, count, workload, and checksum rules
- **THEN** validation and replay succeed without requiring v2 fields

#### Scenario: Validate a schema v2 real dataset
- **WHEN** parent linkage, real provenance, Chinese text, ordered offsets, counts, real workload, and checksums are valid
- **THEN** validation succeeds and reports identical real and effective workload

#### Scenario: Validate a schema v2 enriched dataset
- **WHEN** all real and synthetic provenance rules, configured ratio, parent linkage, Chinese text, counts, real workload, effective workload, and checksums are valid
- **THEN** validation succeeds and reports real and synthetic counts separately

#### Scenario: Reject an unsafe or corrupt dataset
- **WHEN** a dataset contains an unsupported schema, invalid parent relationship, non-monotonic time, mismatched counts, checksum mismatch, residual identifying text, non-Chinese user-visible text, illegal actor, or incomplete synthetic marker
- **THEN** validation fails with a machine-readable reason before replay begins

### Requirement: Workload qualification
The system SHALL classify datasets using replyable-message counts in 60-second windows and SHALL require at least 80 percent of observed windows to fall inside the selected heat tier. Schema v2 SHALL sample rolling windows every second and SHALL use only `origin=real` events for canonical workload; effective workload SHALL include all events.

#### Scenario: Classify schema v2 heat tiers
- **WHEN** a schema v2 dataset is validated
- **THEN** low heat is 1–10, medium heat is 11–60, and high heat is 61–300 real replyable messages in each one-second-stepped rolling minute

#### Scenario: Preserve schema v1 workload compatibility
- **WHEN** a schema v1 dataset is validated
- **THEN** it uses the original aligned 60-second workload calculation

#### Scenario: Ignore synthetic events for canonical heat
- **WHEN** an enriched schema v2 dataset is validated
- **THEN** synthetic events affect effective workload and do not affect heat-tier qualification

#### Scenario: Reject an unrepresentative source
- **WHEN** fewer than 80 percent of the applicable windows fall inside the selected tier
- **THEN** workload qualification fails and the dataset cannot become a canonical baseline

### Requirement: Evaluation CLI and evidence
The system SHALL expose `capture`, `clean`, `validate`, `replay`, and `report` commands and SHALL write generated datasets and evidence outside tracked source fixtures.

#### Scenario: Clean a source dataset
- **WHEN** an operator invokes `clean` with a validated source, balanced profile, target language, fixed seed, LLM profile, and ratio
- **THEN** the CLI creates paired v2 variants, optional medium derivation, and cleaning evidence atomically

#### Scenario: Run a transport evaluation
- **WHEN** an operator replays a dataset in transport mode
- **THEN** the runner uses a deterministic stub reply processor and records event reconciliation, scheduling lag, queue, lifecycle, resource, real-origin, and synthetic-origin metrics

#### Scenario: Generate a report
- **WHEN** a replay result and optional completed scoring worksheet are provided
- **THEN** the reporter writes JSON and Markdown summaries, a complete sanitized conversation JSONL file, and a deterministic manual-scoring CSV with real and synthetic results separated
- **AND** it creates an explicit post-run safety assessment form and a non-authoritative hash-only content audit without copying matched reply text

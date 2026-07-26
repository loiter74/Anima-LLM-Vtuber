## ADDED Requirements

### Requirement: Review pruning is explicit and dry-run-first
The local review maintenance command SHALL report candidate runs without deleting them unless the operator explicitly enables apply mode.

#### Scenario: Default invocation
- **WHEN** the operator runs review pruning without `--apply`
- **THEN** the command SHALL report candidate run IDs, statuses, file counts, and total bytes
- **AND** it SHALL NOT remove any filesystem entry

#### Scenario: Apply invocation
- **WHEN** the operator repeats a validated prune request with `--apply`
- **THEN** the command SHALL remove exactly the reported candidate run directories
- **AND** it SHALL report the actual removed count and bytes

### Requirement: Canonical evidence is retained by allowlist
The maintenance command SHALL accept repeated canonical run identifiers and SHALL exclude them from every deletion policy.

#### Scenario: Canonical run also matches a deletion status
- **WHEN** a keep-listed run is marked failed, running, or superseded passed
- **THEN** the command SHALL retain the run
- **AND** it SHALL identify the keep rule in the dry-run report

### Requirement: Pruning is path bounded
The maintenance command MUST limit deletions to immediate run directories below the configured local review root.

#### Scenario: Target escapes the review root
- **WHEN** a malformed identifier, traversal segment, symlink, reparse point, or nested path would escape the review root
- **THEN** the command SHALL reject the request before deleting any run

#### Scenario: Pruning is repeated
- **WHEN** apply mode is run again after all candidates were removed
- **THEN** the command SHALL complete successfully with zero removals

### Requirement: Accepted evidence survives cleanup
Repository cleanup SHALL retain the approved frozen livestream rounds, the v2 stable-round pair, and one latest successful TTS failover acceptance run.

#### Scenario: Replacement TTS acceptance succeeds
- **WHEN** a fresh TTS failover review passes all technical assertions after the refactor
- **THEN** that run SHALL become the canonical TTS evidence
- **AND** earlier TTS runs MAY be pruned according to the explicit apply policy

#### Scenario: Replacement acceptance fails
- **WHEN** fresh TTS failover acceptance does not pass
- **THEN** the previously approved canonical TTS run SHALL remain retained

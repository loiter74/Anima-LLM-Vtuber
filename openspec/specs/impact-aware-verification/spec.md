# impact-aware-verification Specification

## Purpose
TBD - created by archiving change add-impact-aware-quality-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Typed verification catalog
The repository SHALL define components and verification groups in one versioned declarative manifest. Group domain, kind, runner, isolation, capability, timeout, dependency, and full-suite fields SHALL use validated typed values rather than free-form execution semantics.

#### Scenario: Invalid catalog reference
- **WHEN** a component or group references an unknown group ID, an unsupported runner, or a cyclic execution dependency
- **THEN** manifest validation SHALL fail before a plan or command is executed

### Requirement: Portable change discovery
The planner SHALL accept explicit paths, the current Git worktree, or a base/head revision range and SHALL normalize modified, staged, untracked, deleted, and renamed paths to repository-relative POSIX form.

#### Scenario: Dirty Windows worktree
- **WHEN** a local worktree contains staged, unstaged, untracked, renamed, or Unicode paths on Windows
- **THEN** the planner SHALL produce one normalized change record per effective path without shell-dependent parsing

### Requirement: Deterministic explainable planning
The planner SHALL generate a versioned `VerificationPlan` containing normalized changes, selected group IDs, selection reasons, capabilities, fallbacks, revision identity, manifest hash, and a stable plan hash. Identical normalized inputs and manifests SHALL produce identical plans.

#### Scenario: Repeat the same plan
- **WHEN** planning is repeated with the same tier, manifest, revisions, and normalized changes
- **THEN** the selected groups, reasons, manifest hash, and plan hash SHALL be identical

### Requirement: Tiered impact selection
The planner SHALL support `quick`, `affected`, `full`, and `nightly` tiers. Quick SHALL select direct component groups and required smoke checks, affected SHALL expand declared impact relationships and risk policy, full SHALL select eligible hermetic full groups, and nightly SHALL extend full with eligible service groups.

#### Scenario: Server handler affected plan
- **WHEN** an orchestration server handler changes under the affected tier
- **THEN** the plan SHALL include its direct server tests, declared downstream contracts, and route smoke verification with a reason for each group

#### Scenario: Full plan coverage execution
- **WHEN** the full tier is planned
- **THEN** the backend full suite SHALL be selected once with coverage rather than as separate duplicate plain and coverage runs

### Requirement: Conservative risk escalation and fallback
The planner SHALL escalate high-risk and global changes according to policy. Unknown production paths and unavailable revision discovery SHALL never produce a passing empty plan and SHALL fall back to domain-full or repository-full verification.

#### Scenario: Unknown backend production path
- **WHEN** a changed file under `src/animetta` matches no component
- **THEN** the plan SHALL select backend-full verification and record the fallback reason

#### Scenario: Missing base revision
- **WHEN** a requested base revision cannot be resolved after change discovery attempts
- **THEN** the plan SHALL degrade to repository-full verification and record the discovery failure

### Requirement: Explicit capability enforcement
Verification groups SHALL declare required capabilities such as browser, Docker, network, or GPU. A required group whose capability is unavailable SHALL be reported as blocked and SHALL fail the aggregate result rather than being silently skipped.

#### Scenario: Docker group without Docker
- **WHEN** a required service verification group is selected and Docker is unavailable
- **THEN** its result SHALL be `blocked`, include remediation, and prevent an aggregate pass

### Requirement: Safe named-group execution
The executor SHALL run catalogued group IDs through fixed runner implementations using argument arrays and bounded timeouts. It SHALL NOT execute planner-generated or manifest-interpolated shell strings.

#### Scenario: Execute a pytest group
- **WHEN** a frozen plan selects a pytest verification group
- **THEN** the executor SHALL construct the pytest argv from validated targets, execute it without a shell, and bind the result to the plan and manifest hashes

### Requirement: Complete result evidence
Every selected group SHALL produce a versioned result with group ID, required flag, status, exit code, duration, failure kind, artifacts, plan hash, and manifest hash. Required failed, blocked, cancelled, or missing results SHALL prevent aggregate success.

#### Scenario: Required matrix result is absent
- **WHEN** aggregation receives no result for a required planned group
- **THEN** aggregation SHALL fail and identify the missing group

### Requirement: Stable local entrypoints
The repository SHALL expose stable commands for validating the manifest, explaining a path, planning and running quick/affected/full verification, and writing generated evidence outside hand-edited source files.

#### Scenario: Agent plans explicit edits
- **WHEN** an AI agent supplies the paths it modified to the quick command
- **THEN** the command SHALL display and optionally persist the selected groups and reasons before execution


## Purpose
Defines the accepted behavior and requirements for the skill-persistence capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: SkillLibrary persists to SQLite
The system SHALL persist learned, predefined, revision, validation, trust, and execution-record skill data to SQLite so that identity and trust survive restarts, and an acknowledged trust-changing write MUST be transactionally durable before Live can observe it.

#### Scenario: Learned skill survives restart
- **WHEN** a candidate skill revision is saved and the bot process restarts
- **THEN** its immutable program, provenance, execution statistics, and environment validations SHALL remain available

#### Scenario: Predefined skills loaded at startup
- **WHEN** SkillLibrary starts with a database path
- **THEN** the existing predefined skill definitions and all previously persisted learned definitions SHALL load or migrate without duplicate identity

#### Scenario: SQLite database created on first run
- **WHEN** the bot starts with a skill database path that does not exist
- **THEN** the system SHALL create the required definition, revision, validation, trust, and execution-record tables

#### Scenario: Cache and database disagree
- **WHEN** an in-memory cache differs from authoritative persisted revision or trust data
- **THEN** the system SHALL use the persisted data for Live eligibility
- **THEN** it SHALL NOT expose an uncommitted trust promotion

### Requirement: Skill data persisted correctly
The system SHALL serialize all skill fields to SQLite including nested structures.

#### Scenario: SkillStep list serialization
- **WHEN** a skill with steps is saved to SQLite
- **THEN** the steps list SHALL be serialized as JSON in the steps_json column
- **AND** deserialized back to SkillStep objects on load

#### Scenario: Tags serialization
- **WHEN** a skill with tags is saved to SQLite
- **THEN** the tags list SHALL be serialized as JSON in the tags_json column
- **AND** deserialized back to a list on load

#### Scenario: Timestamp preservation
- **WHEN** a skill has a last_used timestamp
- **THEN** it SHALL be stored as ISO format string in SQLite
- **AND** restored as the same timestamp on load

### Requirement: Persist skill trust stage and provenance
Skill persistence SHALL store trust per immutable skill revision and stable environment profile, including source command/step, policy report, independent learning and validation evidence references, compatibility profile, demotion history, and quarantine reason.

#### Scenario: Candidate survives restart
- **WHEN** a candidate revision is saved and the process restarts
- **THEN** it SHALL remain ineligible for Live until a valid environment-scoped trust record exists

#### Scenario: Trusted revision reloads in matching environment
- **WHEN** an independently validated revision is reloaded under a compatible environment profile
- **THEN** Live SHALL be able to consider it with validation provenance intact

#### Scenario: Trusted revision appears in another environment
- **WHEN** a trusted revision is loaded under a stable environment profile for which it lacks validation
- **THEN** it SHALL NOT inherit trust from the prior environment

### Requirement: Demotion preserves audit history
Repeated ordinary Live failures SHALL demote only the affected revision/environment validation, while policy violations or unexplained mutation SHALL quarantine the revision across environments, and neither operation SHALL delete execution or validation history.

#### Scenario: Trusted revision crosses ordinary failure threshold
- **WHEN** a trusted revision reaches the configured consecutive-failure threshold in one environment profile
- **THEN** persistence SHALL record environment-specific demotion and Live SHALL stop selecting it there
- **THEN** unrelated environment validations SHALL remain unchanged

#### Scenario: Revision violates policy
- **WHEN** execution attributes an unauthorized capability or unexplained world mutation to a revision
- **THEN** persistence SHALL quarantine that revision across all environment profiles while preserving evidence

### Requirement: Production skills use immutable declarative revisions
The system SHALL persist production skills as immutable, content-addressed declarative Skill IR revisions with typed parameters, authorized capabilities, bounded steps, preconditions, postconditions, portability, and static cost bounds.

#### Scenario: Skill program changes
- **WHEN** any normalized Skill IR content changes
- **THEN** the system SHALL create a new revision hash
- **THEN** prior revision validation SHALL NOT transfer automatically

#### Scenario: Skill program contains arbitrary code
- **WHEN** a candidate contains executable JavaScript, arbitrary evaluation, recursion, dynamic capability names, or unbounded loops
- **THEN** persistence SHALL refuse to register it as a production-eligible Skill IR revision

### Requirement: Legacy executable skills migrate without inherited trust
Existing JavaScript or code-body skills SHALL migrate non-destructively as `legacy_untrusted` and MUST NOT inherit global validated or trusted flags into the environment-scoped trust model.

#### Scenario: Legacy validated skill is migrated
- **WHEN** migration encounters an old executable skill marked validated
- **THEN** it SHALL preserve the original record and audit metadata
- **THEN** any generated Skill IR conversion SHALL begin as a candidate requiring independent validation

### Requirement: Skill execution attribution controls trust changes
Every skill execution SHALL be classified as success, skill-attributable failure, environment failure, caller/system cancellation, runtime/infrastructure failure, or policy/unexplained mutation before trust aggregates change.

#### Scenario: Runtime disconnects during skill execution
- **WHEN** a trusted revision cannot complete because the runtime disconnects
- **THEN** persistence SHALL record the execution but SHALL NOT increment the revision's attributable-failure or demotion counters

#### Scenario: Skill fails under satisfied declared preconditions
- **WHEN** valid attributable receipts prove the revision's plan or postconditions failed under its satisfied preconditions
- **THEN** persistence SHALL increment the environment-specific attributable-failure counters

#### Scenario: Skill causes policy violation
- **WHEN** evidence attributes unauthorized capability use, budget-contract violation, or unexplained world mutation to a revision
- **THEN** persistence SHALL quarantine the revision globally

### Requirement: Live ranking is deterministic among eligible trusted revisions
The skill catalog SHALL first exclude every ineligible revision and then rank remaining revisions deterministically by goal match tier, satisfied constraints, exact environment trust, attributable reliability, observed budget/duration cost, and stable revision-hash tie-break.

#### Scenario: Two eligible revisions have equal observed performance
- **WHEN** all earlier ranking keys are equal
- **THEN** the catalog SHALL use immutable revision hash order so repeated selection over the same evidence produces the same result


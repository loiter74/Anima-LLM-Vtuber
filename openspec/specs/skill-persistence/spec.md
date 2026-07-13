## Purpose
Defines the accepted behavior and requirements for the skill-persistence capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: SkillLibrary persists to SQLite
The system SHALL persist all learned and predefined skills to a SQLite database so that skills survive bot restarts.

#### Scenario: Learned skill survives restart
- **WHEN** the bot extracts a new skill via SkillExtractor and saves it to SkillLibrary
- **AND** the bot process restarts
- **THEN** the skill SHALL be available in SkillLibrary after restart with its success_count, fail_count, and avg_duration preserved

#### Scenario: Predefined skills loaded at startup
- **WHEN** the bot starts and SkillLibrary is initialized with a db_path
- **THEN** all 9 predefined skills from predefined_skills.py SHALL be loaded into the library
- **AND** any previously learned skills SHALL be loaded from the SQLite database

#### Scenario: SQLite database created on first run
- **WHEN** the bot starts for the first time with a db_path that does not exist
- **THEN** the system SHALL create the SQLite database and the skills table
- **AND** populate it with predefined skills

#### Scenario: In-memory dict remains primary store
- **WHEN** a skill is looked up via match_skills() or get_skill()
- **THEN** the lookup SHALL read from the in-memory dict (not SQLite)
- **AND** SQLite writes SHALL happen asynchronously via asyncio.create_task() to avoid blocking the tick loop

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
Skill persistence SHALL distinguish candidate and trusted stages and SHALL store source session, source task, policy result, evidence references, validation session, and environment fingerprint.

#### Scenario: Candidate survives restart
- **WHEN** a candidate skill is saved and the process restarts
- **THEN** it SHALL remain candidate with its provenance intact and SHALL NOT become selectable by live mode

#### Scenario: Trusted skill reloads
- **WHEN** an independently validated trusted skill is reloaded
- **THEN** live mode SHALL be able to select it with its validation provenance intact

### Requirement: Demotion preserves audit history
Repeated live failures SHALL demote a trusted skill to candidate without deleting its execution and validation history.

#### Scenario: Trusted skill crosses failure threshold
- **WHEN** a trusted skill reaches the configured consecutive failure threshold
- **THEN** persistence SHALL record its demotion and live mode SHALL stop selecting it

## ADDED Requirements

### Requirement: Balanced contextual cleaning
The system SHALL clean only validated sanitized datasets and SHALL retain replyable messages with recognizable conversational intent while removing deterministic noise and semantically unclear content.

#### Scenario: Remove deterministic noise
- **WHEN** a replyable message is empty, symbol-only, laughter-only, a standalone emote or meaningless abbreviation, a same-actor short-window duplicate, or repeated copypasta
- **THEN** the cleaner drops it with a stable machine-readable reason

#### Scenario: Preserve recognizable interaction
- **WHEN** a message expresses a question, game instruction, opinion, greeting, emotion, correction, or understandable contextual reply
- **THEN** the cleaner retains it and records an intent

#### Scenario: Resolve ambiguous intent with context
- **WHEN** deterministic rules cannot decide whether a message has recognizable intent
- **THEN** the semantic processor receives the sanitized message with at most three preceding and three following messages within twenty seconds
- **AND** a malformed, unavailable, or mock production processor causes an atomic failure

### Requirement: Chinese-localized output
The system SHALL emit Chinese-dominant user-visible text for every retained or generated replyable event.

#### Scenario: Translate a retained foreign message
- **WHEN** a retained message is not Chinese-dominant
- **THEN** the semantic processor returns concise natural Chinese suitable for livestream chat while preserving allowlisted proper nouns and acronyms

#### Scenario: Reject untranslated output
- **WHEN** a processed replyable event contains a consecutive untranslated English sentence after allowlisted names are removed
- **THEN** validation fails before the dataset is published

### Requirement: Paired immutable variants
The system SHALL leave source datasets unchanged and SHALL atomically publish a real-only variant and a separately enriched variant.

#### Scenario: Publish a successful pair
- **WHEN** source validation, cleaning, enrichment, checksum, provenance, language, and workload validation all succeed
- **THEN** the command publishes `<source>-clean-real-v2` and `<source>-clean-enriched-v2` without overwriting existing directories

#### Scenario: Abort a partial pair
- **WHEN** any stage fails
- **THEN** neither output variant is published and staging data is removed

### Requirement: Real-only medium derivation
The system SHALL derive medium heat from cleaned high-heat real events using a fixed seed and SHALL preserve original relative offsets and source sequence references.

#### Scenario: Qualify a derived medium dataset
- **WHEN** medium derivation is requested with a target of 40 messages per minute
- **THEN** at least 80 percent of one-second-stepped rolling 60-second windows contain 11–60 real replyable events

#### Scenario: Reject unqualified derivation
- **WHEN** the available real events cannot satisfy medium-tier workload qualification
- **THEN** derivation fails without adding synthetic events or changing source offsets

### Requirement: Real-only high-heat calibration
The system SHALL preserve a cleaned high-heat source by applying the smallest qualifying deterministic continuous time-compression factor, without changing event order or adding generated traffic.

#### Scenario: Qualify a cleaned high dataset
- **WHEN** retained real events no longer meet the high-tier rolling workload at their original offsets
- **THEN** the pipeline tests factors from 1.00 through 2.00 in deterministic 0.05 increments
- **AND** accepts the first factor where at least 80 percent of rolling windows contain 61–300 real replyable events and the resulting duration is at least 90 minutes
- **AND** the resulting timeline can complete the configured 30-, 60-, and 80-minute high-heat burst windows
- **AND** records the factor and original duration in derivation metadata

#### Scenario: Reject artificial high-heat repair
- **WHEN** no bounded continuous time compression qualifies
- **THEN** generation fails without adding synthetic events, reordering real events, concatenating another source, or exceeding 2x compression

### Requirement: Marked scenario enrichment
The system SHALL add exactly the configured synthetic ratio and SHALL make every generated event visibly and machine-readably distinguishable from real events.

#### Scenario: Generate the approved synthetic budget
- **WHEN** enrichment runs at ratio 0.10 over N real replyable events
- **THEN** it adds exactly `ceil(N * 0.10)` replyable events
- **AND** synthetic gift and super-chat events together are approximately one percent of N, clamped to 6–30 and to the available synthetic budget

#### Scenario: Validate synthetic provenance
- **WHEN** a synthetic event is written
- **THEN** its text starts with `[合成补充]`, its actor matches `synthetic_NNNN`, and its payload contains `origin=synthetic`, a scenario, and a parent sequence

#### Scenario: Cover interaction scenarios
- **WHEN** a dataset is enriched
- **THEN** its deterministic scenario rotation covers direct questions, contextual follow-ups, correction or challenge, topic shifts, emotional support, privacy or safety boundaries, gift acknowledgement, and super-chat priority handling where the event budget permits

### Requirement: Auditable cleaning evidence
The system SHALL report cleaning and enrichment results without copying original foreign text into the generated dataset or evidence bundle.

#### Scenario: Generate evidence
- **WHEN** cleaning completes
- **THEN** JSON and Markdown summarize retention, drop reasons, translations, intents, synthetic scenarios, and real/effective workload
- **AND** a fixed-seed CSV samples retained, dropped, and synthetic decisions using sequence references and hashes

#### Scenario: Cache semantic decisions safely
- **WHEN** an accepted semantic decision is cached
- **THEN** the cache stores only source checksum, source sequence, text hash, decision, intent, and Chinese result
- **AND** it stores no original input text, credential, URL, room identifier, UID, or nickname

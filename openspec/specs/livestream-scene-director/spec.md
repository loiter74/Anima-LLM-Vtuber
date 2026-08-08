# livestream-scene-director Specification

## Purpose
TBD - created by archiving change add-livestream-scene-director. Update Purpose after archive.
## Requirements
### Requirement: Room-wide livestream event observation
The system SHALL normalize and observe every supported event received by the active livestream room before reply admission decides whether it will receive an AI answer.

#### Scenario: Rejected danmaku still affects scene evidence
- **WHEN** a danmaku is displayed but rejected by reply admission
- **THEN** the scene runtime SHALL retain its normalized event and include it in rolling metrics

#### Scenario: Room generation changes
- **WHEN** the livestream switches rooms or stops and advances its generation
- **THEN** the scene runtime SHALL cancel pending work and reset transient state so an old-room patch cannot affect the new room

### Requirement: Typed scene contracts and single-writer state reduction
The system SHALL validate scene events, evidence, state, patches, and guidance with strict versioned Pydantic contracts, and SHALL modify `LiveSceneState` only through the scene reducer.

#### Scenario: Current patch is applied
- **WHEN** a valid patch has `base_revision` equal to the current state revision
- **THEN** the reducer SHALL produce a new state with the next revision and the patch's consumed event cursor

#### Scenario: Stale patch is received
- **WHEN** a patch targets an older state revision
- **THEN** the reducer SHALL reject it without changing the current scene state

### Requirement: History-neutral structured scene reflection
The Scene Analyzer SHALL reuse the selected LLM engine only through a provider-native message-based call that does not mutate main conversation history.

#### Scenario: Native message call is available
- **WHEN** the configured provider overrides `LLMInterface.chat_messages`
- **THEN** the analyzer SHALL call it with explicit messages, deterministic sampling, bounded output, JSON response mode, and a timeout
- **THEN** the provider's main conversation history SHALL be unchanged after the call

#### Scenario: Native message call is unavailable
- **WHEN** the configured provider only inherits the default history-mutating message fallback
- **THEN** the analyzer SHALL skip the LLM reflection and return a typed degraded result
- **THEN** it SHALL NOT call `chat()` or clear and restore shared history

### Requirement: Periodic and event-triggered cached reflection
The scene runtime SHALL refresh scene state asynchronously based on elapsed time, accumulated events, and critical signals while coalescing concurrent triggers.

#### Scenario: Normal threshold is reached
- **WHEN** either 30 seconds or 30 new effective events have accumulated since the last reflection
- **THEN** the runtime SHALL schedule one background reflection if call budget is available

#### Scenario: Multiple triggers arrive during reflection
- **WHEN** another periodic or critical trigger occurs while reflection is running
- **THEN** the runtime SHALL coalesce it into at most one subsequent refresh and SHALL NOT start a concurrent analyzer call

#### Scenario: Reply needs guidance during refresh
- **WHEN** a reply begins while reflection is already running
- **THEN** guidance lookup SHALL wait no more than the configured 300 ms budget
- **THEN** timeout SHALL return cached state plus deterministic latest-window corrections

### Requirement: Bounded guidance composition
The system SHALL project current scene state into a compact `SceneGuidance` that contains behavior boundaries but no authored final answer.

#### Scenario: Retriever returns candidates
- **WHEN** technique and approved-meme retrievers return relevant candidates
- **THEN** guidance SHALL contain at most one selected technique and one selected meme policy
- **THEN** it SHALL NOT include full candidate lists or retrieval documents

#### Scenario: Retriever returns no candidates
- **WHEN** no technique or meme is relevant
- **THEN** guidance SHALL remain valid with absent technique and a `none` meme action

### Requirement: Fail-open rollout modes
The scene director SHALL support `off`, `shadow`, and `active` modes and SHALL never make scene-analysis failure prevent the main reply path.

#### Scenario: Shadow mode
- **WHEN** mode is `shadow`
- **THEN** the runtime SHALL produce state, guidance, and metrics but SHALL NOT attach guidance to the main LLM turn

#### Scenario: Active analyzer failure
- **WHEN** reflection times out, returns invalid JSON, fails schema validation, or exceeds call budget
- **THEN** the runtime SHALL retain the last valid state, mark guidance degraded, and allow the main reply to continue

#### Scenario: Off mode
- **WHEN** mode is `off`
- **THEN** the runtime SHALL not schedule LLM reflections and SHALL not attach scene guidance

### Requirement: Local-Qwen Docker acceptance isolation
The repository SHALL provide a dedicated self-test runtime selection that uses the persistent local Qwen TTS worker without changing the production provider identity.

#### Scenario: Self-test startup
- **WHEN** the local Docker acceptance lifecycle starts Animetta in self-test mode
- **THEN** the effective profile SHALL select `qwen-alice` as TTS
- **THEN** the Qwen worker SHALL pass its authenticated preflight before Animetta starts

#### Scenario: Production startup remains unchanged
- **WHEN** the normal production lifecycle starts Animetta
- **THEN** the effective production profile SHALL continue to select `dashscope-seren`
- **THEN** a self-test acceptance result SHALL NOT be represented as production-provider acceptance


## Purpose
Defines the accepted behavior and requirements for the service-pool capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: LLM/TTS/ASR engines are globally shared
The system SHALL construct a single shared instance of LLM, TTS, and ASR from the active EffectiveConfig and reuse those exact instances for all sessions. The MinecraftBridge SHALL access the shared LLM engine via ServicePool for skill extraction. Each constructed engine SHALL retain configured and resolved identity metadata.

#### Scenario: Multiple sessions share engines
- **WHEN** two or more sessions are created
- **THEN** they SHALL use the same LLM engine, TTS engine, and ASR engine instances

#### Scenario: Each session has own VAD and Memory
- **WHEN** a session is created
- **THEN** it SHALL have its own VAD engine instance and Memory system instance
- **AND** its VAD SHALL be constructed from the same EffectiveConfig version and selected provider identity

#### Scenario: MinecraftBridge accesses LLM via ServicePool
- **WHEN** MinecraftBridge is constructed with a ServicePool reference
- **AND** `_start_autonomous()` is called
- **THEN** the system SHALL extract the LLM service via `service_pool.get_service("llm")`
- **AND** pass it to SkillExtractor and MinecraftPlanner

#### Scenario: Graceful degradation when ServicePool unavailable
- **WHEN** MinecraftBridge is constructed without a ServicePool (`service_pool=None`)
- **THEN** `_start_autonomous()` SHALL log a warning
- **AND** create AutonomousLoop without learning components
- **AND** the bot SHALL still function with pure rule-based behavior

#### Scenario: ServicePool initializes from configuration
- **WHEN** ServicePool initializes for an explicit profile
- **THEN** every service factory SHALL receive the same EffectiveConfig snapshot and ProviderPolicy
- **AND** no factory SHALL independently load YAML or provider-selection environment variables

#### Scenario: Real service construction fails
- **WHEN** a `smoke` or `production` provider import, validation, or construction fails
- **THEN** ServicePool initialization SHALL fail with the typed sanitized cause
- **AND** it SHALL not create a Mock replacement

### Requirement: Shared LLM receives runtime reload updates
The service pool SHALL apply successful allowlisted runtime reload updates to the shared LLM engine without requiring engine recreation and SHALL associate the update with the newly published EffectiveConfig version.

#### Scenario: Lightweight LLM fields update on reload
- **WHEN** runtime reload succeeds with changed allowlisted lightweight LLM settings
- **THEN** the shared LLM engine SHALL receive supported updates for temperature, top-p, max tokens, and provider-specific non-identity thinking settings
- **THEN** future sessions using the pool SHALL observe those updated settings and new EffectiveConfig version

#### Scenario: Shared LLM prompt updates on reload
- **WHEN** runtime reload succeeds and the shared LLM engine supports `set_system_prompt`
- **THEN** the service pool SHALL apply the effective reloaded system prompt to that LLM engine

#### Scenario: LLM identity change is requested
- **WHEN** a candidate reload changes LLM provider, model, endpoint, or authentication reference
- **THEN** ServicePool SHALL receive no update and keep the previous engine and EffectiveConfig version
- **AND** the reload result SHALL require a restart

### Requirement: Runtime reload preserves shared engine lifecycle
The service pool SHALL not restart or close shared LLM, TTS, or ASR engines as part of an allowed runtime reload and SHALL reject lifecycle-field changes before they reach those engines.

#### Scenario: Reload does not recreate shared engines
- **WHEN** runtime reload succeeds
- **THEN** the shared LLM, TTS, and ASR engine object identities SHALL remain unchanged
- **THEN** only supported lightweight fields and prompts SHALL be updated
- **AND** configured/resolved provider identities SHALL remain equal to their pre-reload values

#### Scenario: Reload failure leaves shared engines unchanged
- **WHEN** runtime reload fails validation or requires restart
- **THEN** the shared LLM, TTS, and ASR engines SHALL retain their previous settings, prompt, identity metadata, and EffectiveConfig version

### Requirement: ServicePool shares one composite TTS
ServicePool SHALL construct and share one composite TTS instance whose child lifecycle is owned and closed exactly once by the composite.

#### Scenario: One child preloads
- **WHEN** one composite child preloads successfully and the other fails
- **THEN** ServicePool SHALL retain the composite engine and become ready in degraded mode

#### Scenario: Composite shutdown
- **WHEN** ServicePool shuts down
- **THEN** both child engines SHALL be closed exactly once
- **AND** later child completion SHALL NOT make ServicePool ready again

### Requirement: ServicePool reports configured and resolved identities
ServicePool SHALL expose a sanitized status snapshot for LLM, ASR, TTS, and VAD containing EffectiveConfig version, configured type/model/voice, resolved type/model/voice, readiness, and a typed mismatch/failure category.

#### Scenario: All services resolve as configured
- **WHEN** ServicePool and required remote providers initialize successfully
- **THEN** every configured identity SHALL equal its resolved identity
- **AND** the snapshot SHALL be eligible for application readiness and frontend display

#### Scenario: Service identity mismatches
- **WHEN** a constructed engine or remote identity differs from EffectiveConfig
- **THEN** the snapshot SHALL mark that service unready with an identity-mismatch category
- **AND** application readiness SHALL fail
- **AND** no secret or sensitive local path SHALL appear in the snapshot


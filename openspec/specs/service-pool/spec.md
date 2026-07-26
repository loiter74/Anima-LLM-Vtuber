## Purpose
Defines the accepted behavior and requirements for the service-pool capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: LLM/TTS/ASR engines are globally shared
The system SHALL maintain a single shared instance of LLM, TTS, and ASR engines that all sessions reuse. The MinecraftBridge SHALL access the shared LLM engine via ServicePool for skill extraction.

#### Scenario: Multiple sessions share engines
- **WHEN** two or more sessions are created
- **THEN** they SHALL use the same LLM engine, TTS engine, and ASR engine instances

#### Scenario: Each session has own VAD and Memory
- **WHEN** a session is created
- **THEN** it SHALL have its own VAD engine instance and Memory system instance

#### Scenario: MinecraftBridge accesses LLM via ServicePool
- **WHEN** MinecraftBridge is constructed with a ServicePool reference
- **AND** _start_autonomous() is called
- **THEN** the system SHALL extract the LLM service via service_pool.get_service("llm")
- **AND** pass it to SkillExtractor and MinecraftPlanner

#### Scenario: Graceful degradation when ServicePool unavailable
- **WHEN** MinecraftBridge is constructed without a ServicePool (service_pool=None)
- **THEN** _start_autonomous() SHALL log a warning
- **AND** create AutonomousLoop without learning components (current behavior)
- **AND** the bot SHALL still function with pure rule-based behavior

### Requirement: Shared LLM receives runtime reload updates
The service pool SHALL apply successful runtime reload updates to the shared LLM engine without requiring engine recreation.

#### Scenario: Lightweight LLM fields update on reload
- **WHEN** runtime reload succeeds with changed lightweight LLM settings
- **THEN** the shared LLM engine SHALL receive supported updates for model, temperature, top-p, max tokens, and provider-specific thinking settings
- **THEN** future sessions using the pool SHALL observe those updated settings

#### Scenario: Shared LLM prompt updates on reload
- **WHEN** runtime reload succeeds and the shared LLM engine supports `set_system_prompt`
- **THEN** the service pool SHALL apply the effective reloaded system prompt to the shared LLM engine

### Requirement: Runtime reload preserves shared engine lifecycle
The service pool SHALL not restart or close shared LLM, TTS, or ASR engines as part of lightweight runtime reload.

#### Scenario: Reload does not recreate shared engines
- **WHEN** runtime reload succeeds
- **THEN** the shared LLM, TTS, and ASR engine object identities SHALL remain unchanged
- **THEN** only supported lightweight fields and prompts SHALL be updated

#### Scenario: Reload failure leaves shared engines unchanged
- **WHEN** runtime reload fails validation
- **THEN** the shared LLM, TTS, and ASR engines SHALL retain their previous settings and prompt

### Requirement: ServicePool shares one composite TTS
ServicePool SHALL construct and share one composite TTS instance whose child lifecycle is owned and closed exactly once by the composite.

#### Scenario: One child preloads
- **WHEN** one composite child preloads successfully and the other fails
- **THEN** ServicePool SHALL retain the composite engine and become ready in degraded mode

#### Scenario: Composite shutdown
- **WHEN** ServicePool shuts down
- **THEN** both child engines SHALL be closed exactly once
- **AND** later child completion SHALL NOT make ServicePool ready again


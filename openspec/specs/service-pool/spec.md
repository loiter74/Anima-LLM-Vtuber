## MODIFIED Requirements

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

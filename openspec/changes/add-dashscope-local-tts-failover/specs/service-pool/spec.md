## ADDED Requirements

### Requirement: ServicePool shares one composite TTS
ServicePool SHALL construct and share one composite TTS instance whose child lifecycle is owned and closed exactly once by the composite.

#### Scenario: One child preloads
- **WHEN** one composite child preloads successfully and the other fails
- **THEN** ServicePool SHALL retain the composite engine and become ready in degraded mode

#### Scenario: Composite shutdown
- **WHEN** ServicePool shuts down
- **THEN** both child engines SHALL be closed exactly once
- **AND** later child completion SHALL NOT make ServicePool ready again

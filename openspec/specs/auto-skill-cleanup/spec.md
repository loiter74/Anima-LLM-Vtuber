## ADDED Requirements

### Requirement: Auto-cleanup runs probabilistically each tick
The system SHALL automatically clean up low-quality skills at the end of each AutonomousLoop tick with a 5% probability.

#### Scenario: Cleanup triggers at 5% probability
- **WHEN** a tick completes and random() < 0.05
- **THEN** the system SHALL call skill_library.cleanup()
- **AND** skills with success_rate < 0.3 AND total executions >= 10 SHALL be removed

#### Scenario: Cleanup does not block the tick
- **WHEN** cleanup is triggered
- **THEN** it SHALL run asynchronously and not delay the next tick

#### Scenario: Predefined skills are never removed
- **WHEN** cleanup runs and a predefined skill has success_rate < 0.3
- **THEN** the predefined skill SHALL NOT be removed (is_learned=False protects it)

### Requirement: Cleanup criteria are configurable
The system SHALL allow cleanup thresholds to be configured.

#### Scenario: Custom success rate threshold
- **WHEN** cleanup_threshold is configured to 0.4
- **THEN** skills with success_rate < 0.4 AND total >= 10 SHALL be removed

#### Scenario: Custom minimum executions
- **WHEN** min_executions_for_cleanup is configured to 20
- **THEN** skills with fewer than 20 total executions SHALL NOT be removed regardless of success_rate

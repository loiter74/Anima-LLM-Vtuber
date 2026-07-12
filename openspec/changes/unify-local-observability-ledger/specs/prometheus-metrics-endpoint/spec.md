## MODIFIED Requirements

### Requirement: Core metric counters exist
The `/metrics` response SHALL include the core Animetta metric families after their mirror is initialized, and those metric values SHALL be driven by committed observation records.

#### Scenario: Controlled node operation commits
- **WHEN** inspection commits one controlled workflow operation
- **THEN** the corresponding `anima_node_duration_seconds_count` value SHALL increase by exactly one

#### Scenario: Metric name exists without activity
- **WHEN** a core metric family is registered but a controlled record does not change its value
- **THEN** metrics inspection SHALL report failure rather than treating name presence as proof of instrumentation

### Requirement: Metrics are registered incrementally
Metrics SHALL be registered by the Prometheus mirror using bounded names and label sets. `/metrics` SHALL remain available before custom observations, but health validation of business instrumentation SHALL require a controlled delta.

#### Scenario: Server has no conversations yet
- **WHEN** `/metrics` is called before custom observations
- **THEN** it SHALL return HTTP 200 with process metrics
- **AND** it SHALL NOT claim that conversation instrumentation has been exercised

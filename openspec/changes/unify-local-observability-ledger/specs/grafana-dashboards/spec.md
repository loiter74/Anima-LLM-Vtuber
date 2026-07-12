## MODIFIED Requirements

### Requirement: Overview Dashboard
The overview dashboard SHALL derive request rate, outcome rate, critical-path latency, degradation rate, cost, and active sessions from ledger-backed Prometheus metrics. Failed, degraded, cancelled, and aborted traces SHALL remain distinguishable.

#### Scenario: Mixed outcomes are present
- **WHEN** successful, degraded, and failed turns have committed
- **THEN** the overview SHALL display separate counts/rates rather than treating all non-exception returns as success

### Requirement: LangGraph Pipeline Dashboard
The pipeline dashboard SHALL display actual profile-specific workflow operation names and durations. It SHALL not assume the legacy route/ASR/LLM/Tool/TTS/Emotion/Output topology.

#### Scenario: Golden traffic is selected
- **WHEN** the dashboard filters to golden profile
- **THEN** panels SHALL include reasoner, anima_composer, reply_output, and performance_output operations

#### Scenario: Standard traffic is selected
- **WHEN** the dashboard filters to standard profile
- **THEN** panels SHALL show the standard nodes and any repeated tool-loop executions that actually committed

### Requirement: Session ID drill-down variable
Dashboards SHALL support bounded operational filtering by runtime profile and provider. Trace-level drill-down SHALL use local dashboard links keyed by task ID rather than exporting task/session IDs as unbounded Prometheus labels.

#### Scenario: Operator opens a trace
- **WHEN** an operator selects a trace from the local dashboard
- **THEN** the local trace detail SHALL show its operation tree and events
- **AND** Prometheus time-series labels SHALL not contain task ID, message ID, conversation ID, or session ID

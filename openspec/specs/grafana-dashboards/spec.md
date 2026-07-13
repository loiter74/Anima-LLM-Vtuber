## Purpose
Defines the accepted behavior and requirements for the grafana-dashboards capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: Grafana auto-provisioned with Prometheus and Tempo datasources
Grafana SHALL be configured via provisioning to automatically connect to Prometheus (port 9090) and Tempo (port 3200) on startup, requiring zero manual configuration.

#### Scenario: Datasources available on first launch
- **WHEN** `docker-compose up -d` starts the observability stack
- **THEN** Grafana at `http://localhost:3000` SHALL have "Prometheus" and "Tempo" listed as configured datasources
- **THEN** both datasources SHALL show "Success" when tested

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

### Requirement: RAG Performance Dashboard
The system SHALL provide a pre-built Grafana dashboard (`03-rag-performance.json`) showing retrieval quality metrics.

#### Scenario: RAG panel data
- **WHEN** RAG retrieval has been active
- **THEN** the RAG Performance dashboard SHALL display:
  - Retrieval latency p50/p95 per strategy
  - Chunks retrieved distribution histogram
  - Top score distribution histogram

### Requirement: Cost and Tokens Dashboard
The system SHALL provide a pre-built Grafana dashboard (`04-cost-and-tokens.json`) showing LLM cost and token usage.

#### Scenario: Cost panel data
- **WHEN** LLM calls have been made
- **THEN** the Cost & Tokens dashboard SHALL display:
  - Cumulative cost curve
  - Token usage trend (input/output stacked by provider)
  - Per-provider cost pie chart
  - Monthly cost forecast via `predict_linear`

### Requirement: Dashboard JSON in version control
All dashboard JSON files SHALL be stored in `observability/grafana/dashboards/` and tracked in git.

#### Scenario: Dashboard loaded from git
- **WHEN** a new developer clones the repository and starts the observability stack
- **THEN** all 4 dashboards SHALL be available in Grafana without manual import

### Requirement: Session ID drill-down variable
Dashboards SHALL support bounded operational filtering by runtime profile and provider. Trace-level drill-down SHALL use local dashboard links keyed by task ID rather than exporting task/session IDs as unbounded Prometheus labels.

#### Scenario: Operator opens a trace
- **WHEN** an operator selects a trace from the local dashboard
- **THEN** the local trace detail SHALL show its operation tree and events
- **AND** Prometheus time-series labels SHALL not contain task ID, message ID, conversation ID, or session ID

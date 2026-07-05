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
The system SHALL provide a pre-built Grafana dashboard (`01-overview.json`) showing high-level metrics.

#### Scenario: Overview panel data
- **WHEN** the Anima backend has been processing conversations for at least 1 minute
- **THEN** the Overview dashboard SHALL display:
  - QPS: `rate(anima_session_messages_total[5m])`
  - End-to-end latency p50/p95/p99 from `anima_node_duration_seconds{node_name="output"}`
  - Error rate: `rate(anima_node_errors_total[5m]) / rate(anima_node_duration_seconds_count[5m]) * 100`
  - Cost rate per hour
  - Active sessions gauge

### Requirement: LangGraph Pipeline Dashboard
The system SHALL provide a pre-built Grafana dashboard (`02-langgraph-pipeline.json`) showing per-node pipeline metrics.

#### Scenario: Pipeline panel data
- **WHEN** conversations have been processed
- **THEN** the Pipeline dashboard SHALL display:
  - Per-node latency stacked bar chart (route/ASR/LLM/Tool/TTS/Emotion/Output)
  - Node error rate heatmap
  - Tool call distribution pie chart
  - LLM call count vs tool call count dual line chart

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
All dashboards SHALL include a `session_id` template variable for filtering data by session.

#### Scenario: Filter by session
- **WHEN** user selects a specific session_id from the dropdown
- **THEN** all panels SHALL update to show only data for that session

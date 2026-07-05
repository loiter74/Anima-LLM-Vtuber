## Purpose
Defines the accepted behavior and requirements for the alerting-rules capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: High error rate alert
The system SHALL fire an `AnimaHighErrorRate` alert when the LLM error rate exceeds 5% for 5 continuous minutes.

#### Scenario: Error rate alert fires
- **WHEN** `rate(anima_llm_errors_total[5m]) / rate(anima_llm_request_duration_seconds_count[5m]) > 0.05` for 5 minutes
- **THEN** an alert SHALL be sent with severity `warning`
- **THEN** the alert SHALL include the current error rate and affected providers in the description

#### Scenario: Error rate recovers
- **WHEN** the error rate drops below 5% after an active alert
- **THEN** a resolved notification SHALL be sent

### Requirement: High latency alert
The system SHALL fire an `AnimaHighLatency` alert when the end-to-end p95 latency exceeds 10 seconds for 5 continuous minutes.

#### Scenario: Latency alert fires
- **WHEN** `histogram_quantile(0.95, anima_node_duration_seconds{node_name="output"}) > 10` for 5 minutes
- **THEN** an alert SHALL be sent with severity `warning`

### Requirement: Monthly cost budget warning
The system SHALL fire an `AnimaCostBudgetWarning` alert when cumulative monthly LLM cost exceeds $40.

#### Scenario: Cost warning fires
- **WHEN** `anima_llm_cost_usd_total` monthly delta exceeds $40
- **THEN** an alert SHALL be sent with severity `warning`
- **THEN** the alert SHALL include the current total cost and the projected monthly cost

### Requirement: Monthly cost budget critical
The system SHALL fire an `AnimaCostBudgetCritical` alert when cumulative monthly LLM cost exceeds $48.

#### Scenario: Cost critical fires
- **WHEN** `anima_llm_cost_usd_total` monthly delta exceeds $48
- **THEN** an alert SHALL be sent with severity `critical`

### Requirement: Service down alert
The system SHALL fire an `AnimaServiceDown` alert when the Anima backend is unreachable for 2 continuous minutes.

#### Scenario: Service down alert fires
- **WHEN** `up{job="anima"} == 0` for 2 minutes
- **THEN** an alert SHALL be sent with severity `critical`
- **THEN** the alert SHALL include the instance that is down

### Requirement: Alert routing via webhook
Alertmanager SHALL route all alerts to a configurable Discord or Slack webhook URL.

#### Scenario: Alert sent to Discord
- **WHEN** any alert fires
- **THEN** Alertmanager SHALL POST a formatted message to the configured Discord webhook URL
- **THEN** the message SHALL include alert name, severity, description, and current value

#### Scenario: No webhook configured
- **WHEN** the webhook URL environment variable is empty
- **THEN** alerts SHALL be logged but no external notification SHALL be sent

### Requirement: Webhook URL in .env, not committed
The webhook URL SHALL be read from an environment variable defined in `.env` and SHALL NOT be committed to git.

#### Scenario: .env.example includes placeholder
- **WHEN** a developer reads `.env.example`
- **THEN** a commented line for `ALERT_WEBHOOK_URL` SHALL be present with instructions

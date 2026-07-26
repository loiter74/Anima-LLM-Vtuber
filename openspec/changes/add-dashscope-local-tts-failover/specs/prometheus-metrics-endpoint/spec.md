## ADDED Requirements

### Requirement: TTS failover metrics use bounded labels
The Prometheus endpoint SHALL expose counters or histograms for actual TTS backend use, failover category, circuit state, first-audio latency, and real-time factor using only bounded labels.

#### Scenario: Billing triggers local fallback
- **WHEN** a billing failure causes one utterance to use local Qwen
- **THEN** the failover counter SHALL increase with fixed backend and billing-category labels

#### Scenario: Speech text is processed
- **WHEN** any TTS request is observed
- **THEN** no metric name or label value SHALL include synthesized text, API credentials, raw exception messages, request IDs, or filesystem paths

## Purpose
Defines the accepted behavior and requirements for the error-resilience capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: LLM timeout triggers mock fallback
When an LLM provider call exceeds a configurable timeout, the system SHALL catch the timeout exception, log the error to StatsStore as an error trace, and automatically switch to the mock LLM provider for the remainder of that conversation turn.

#### Scenario: LLM timeout during streaming
- **WHEN** LLM `astream()` call exceeds 30-second timeout
- **THEN** the timeout exception is caught
- **AND** an error trace is written to StatsStore with node="llm_node" and error_type="timeout"
- **AND** mock LLM provider returns a fallback response
- **AND** the conversation continues through TTS → Emotion → Output nodes
- **AND** Dashboard error rate counter increments

#### Scenario: Normal operation unaffected
- **WHEN** LLM responds within timeout
- **THEN** no fallback is triggered
- **AND** no error trace is recorded

### Requirement: All external services have fallback path
The system SHALL implement fallback for LLM, TTS, and ASR providers. When a real provider fails (timeout, rate-limit, network error, invalid response), the corresponding mock provider SHALL be substituted for that turn only.

#### Scenario: TTS provider rate-limited
- **WHEN** TTS API returns HTTP 429 (rate limit)
- **THEN** error is logged to StatsStore with error_type="rate_limit"
- **AND** mock TTS returns silent audio
- **AND** frontend receives TTS event with mock audio

### Requirement: Fallback is per-turn, not permanent
After a fallback activates for one conversation turn, the next turn SHALL attempt the real provider again. The system SHALL NOT permanently degrade to mock mode.

#### Scenario: Recovery after single failure
- **WHEN** LLM times out on turn N (mock fallback activates)
- **AND** LLM responds normally on turn N+1
- **THEN** real LLM provider is used for turn N+1

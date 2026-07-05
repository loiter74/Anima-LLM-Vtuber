## ADDED Requirements

### Requirement: DeepSeek thinking mode is configurable
The system SHALL allow DeepSeek provider configuration to explicitly set thinking mode for API calls.

#### Scenario: Thinking disabled in config
- **WHEN** DeepSeek config contains `thinking.type: disabled`
- **THEN** DeepSeek API requests SHALL include request extras equivalent to `{"thinking": {"type": "disabled"}}`

#### Scenario: Thinking enabled in config
- **WHEN** DeepSeek config contains `thinking.type: enabled`
- **THEN** DeepSeek API requests SHALL include request extras equivalent to `{"thinking": {"type": "enabled"}}`

#### Scenario: Invalid thinking mode is rejected
- **WHEN** DeepSeek config contains an unsupported thinking mode
- **THEN** config validation SHALL fail before provider calls are made

### Requirement: DeepSeek request extras are passed to every provider call path
The OpenAI-compatible DeepSeek implementation SHALL pass configured DeepSeek request extras to non-streaming, streaming, message-based, and tool-calling chat completion calls.

#### Scenario: Non-streaming call includes thinking extras
- **WHEN** `OpenAILLM.chat()` is used with DeepSeek thinking disabled
- **THEN** the OpenAI SDK create call SHALL include `extra_body` with thinking disabled

#### Scenario: Streaming call includes thinking extras
- **WHEN** `OpenAILLM.chat_stream()` is used with DeepSeek thinking disabled
- **THEN** the streaming create call SHALL include `extra_body` with thinking disabled

#### Scenario: Tool call includes thinking extras
- **WHEN** `chat_with_tools()` is used with DeepSeek thinking disabled
- **THEN** the tool-calling create call SHALL include `extra_body` with thinking disabled

#### Scenario: OpenAI provider remains unchanged by default
- **WHEN** a non-DeepSeek OpenAI config has no request extras
- **THEN** provider calls SHALL NOT include DeepSeek thinking extras

### Requirement: Anima runtime model policy
The system SHALL define model policy modes for Anima v0.1 so realtime roleplay and complex reasoning select different DeepSeek model/thinking combinations.

#### Scenario: Realtime roleplay selects Flash non-thinking
- **WHEN** the interaction mode is realtime roleplay or danmaku
- **THEN** the selected model SHALL be `deepseek-v4-flash`
- **THEN** thinking mode SHALL be disabled

#### Scenario: Complex reasoning selects Pro thinking
- **WHEN** the interaction mode is complex reasoning
- **THEN** the selected model SHALL be `deepseek-v4-pro`
- **THEN** thinking mode SHALL be enabled

#### Scenario: Routing metadata is recorded
- **WHEN** a DeepSeek runtime policy is selected
- **THEN** the system SHALL record model, policy mode, and thinking mode in metadata
- **THEN** the system SHALL NOT log full prompt text as part of that routing metadata

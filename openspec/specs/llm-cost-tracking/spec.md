## Purpose
Defines the accepted behavior and requirements for the llm-cost-tracking capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Provider pricing table
The system SHALL maintain a `PROVIDER_PRICING` dictionary mapping `(provider, model)` to `(input_price_per_1k_tokens, output_price_per_1k_tokens)` in USD.

#### Scenario: Pricing lookup
- **WHEN** `calculate_cost("openai", "gpt-4o-mini", input_tokens=1500, output_tokens=800)` is called
- **THEN** the function SHALL return `(1500/1000 * input_price) + (800/1000 * output_price)` in USD

#### Scenario: Unlisted model defaults to zero
- **WHEN** a model is not in the pricing table
- **THEN** `calculate_cost` SHALL return `0.0` and log a warning

#### Scenario: Free providers return zero
- **WHEN** `calculate_cost("edge_tts", "default", 0, 0)` is called
- **THEN** the function SHALL return `0.0`

### Requirement: Covered providers
The pricing table SHALL cover at minimum: DeepSeek, GLM, OpenAI, Edge TTS (free), GPT-SoVITS (local/free).

#### Scenario: DeepSeek pricing available
- **WHEN** LLM provider is "deepseek" with model "deepseek-chat"
- **THEN** a valid pricing entry SHALL exist in PROVIDER_PRICING

### Requirement: Pricing update reminder
The `PROVIDER_PRICING` dictionary SHALL include a comment with the last update date, serving as a reminder to periodically refresh prices.

#### Scenario: Date comment present
- **WHEN** a developer opens `cost_calculator.py`
- **THEN** a comment `# TODO: Update pricing as of YYYY-MM-DD` SHALL be visible above the pricing dictionary

### Requirement: LLM cost counter metric
The system SHALL record `anima_llm_cost_usd_total` Counter, labeled with `provider` and `model`, incrementing by the calculated cost after each LLM call.

#### Scenario: Cost recorded after LLM call
- **WHEN** OpenAI chat completion uses 1500 input tokens and 800 output tokens
- **THEN** `anima_llm_cost_usd_total{provider="openai", model="gpt-4o-mini"}` SHALL increment by the calculated USD cost

### Requirement: Token extraction from OpenAI/DeepSeek responses
The OpenAILLM implementation SHALL extract `response.usage.prompt_tokens` and `response.usage.completion_tokens` from every non-streaming API response and make them available for metrics recording.

#### Scenario: Non-streaming token extraction
- **WHEN** `OpenAILLM.chat()` completes a chat completion
- **THEN** the token counts from `response.usage` SHALL be captured before the response object is discarded

#### Scenario: Streaming token extraction from final chunk
- **WHEN** `OpenAILLM.chat_stream()` completes an async generator
- **THEN** if the final chunk contains usage data, token counts SHALL be extracted

### Requirement: Token extraction from GLM responses
The existing `GLMLLM._track_usage()` method SHALL be integrated with the metrics pipeline so its token data feeds into `anima_llm_tokens_total`.

#### Scenario: GLM token tracking feeds metrics
- **WHEN** `GLMLLM.chat()` tracks usage via `_track_usage()`
- **THEN** the tracked token counts SHALL be recorded in `anima_llm_tokens_total`

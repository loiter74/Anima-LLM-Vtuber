## Purpose
Defines the accepted behavior and requirements for the conversation-fix capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: AI conversation response display
The system SHALL correctly display AI responses in the frontend chat interface after the user sends a text message.

#### Scenario: Normal text conversation
- **WHEN** user sends a text message via `text_input` Socket.IO event
- **THEN** the backend SHALL process the message through the LangGraph pipeline
- **THEN** the `output_node` SHALL emit a `sentence` Socket.IO event with the AI response text
- **THEN** the frontend SHALL display the response as an assistant chat message
- **THEN** the frontend SHALL send a `control` event with `signal: conversation-end`

### Requirement: Environment variable loading
The system SHALL automatically load variables from a `.env` file at startup and expand `${VAR}` placeholders in YAML configuration files.

#### Scenario: API key from .env
- **WHEN** a service configuration uses `${DEEPSEEK_API_KEY}` as the API key value
- **WHEN** the `DEEPSEEK_API_KEY` variable exists in a `.env` file in the project root directory
- **THEN** `AppConfig.from_yaml()` SHALL resolve the placeholder to the actual value from the `.env` file
- **THEN** the LLM service SHALL be created with the resolved API key

### Requirement: OpenAI-compatible LLM provider instantiation
The `OpenAILLM.from_config()` method SHALL accept both `OpenAILLMConfig` and `DeepSeekLLMConfig` (and any other OpenAI API-compatible config).

#### Scenario: DeepSeek provider instantiation
- **WHEN** `LLMFactory.create_from_config()` is called with a `DeepSeekLLMConfig` object
- **THEN** it SHALL create an `OpenAILLM` instance (not `MockLLM`)
- **THEN** the instance SHALL use the `api_key`, `model`, `base_url`, `temperature`, and `max_tokens` from the config

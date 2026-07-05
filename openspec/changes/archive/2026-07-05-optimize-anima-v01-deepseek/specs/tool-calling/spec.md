## MODIFIED Requirements

### Requirement: Tool calling works end-to-end
When ChatModel creation succeeds with bound tools, the LLM node SHALL invoke tools during conversation. Tool-calling prompt delivery SHALL use the compiled prompt contract and SHALL preserve provider request extras such as DeepSeek thinking mode.

#### Scenario: LLM calls tool via ChatModel binding
- **WHEN** a user message triggers a tool call (e.g., "搜索今天的新闻")
- **THEN** the LLM node SHALL compile the final prompt through the prompt pipeline
- **THEN** the LLM node SHALL pass the compiled system prompt to the tool-calling provider call
- **THEN** the LLM node SHALL preserve configured provider request extras such as DeepSeek thinking mode
- **THEN** the LLM node SHALL detect tool_calls in the LLM response
- **THEN** the tool_node SHALL execute the requested tool
- **THEN** the LLM SHALL incorporate the tool result into its response

#### Scenario: LLM calls Minecraft tool through compatibility adapter
- **WHEN** a user message triggers an existing Minecraft tool call
- **THEN** the LLM node SHALL compile the final prompt through the prompt pipeline
- **THEN** the tool_node SHALL execute the existing tool name
- **THEN** the Minecraft tool implementation SHALL route through the compatibility adapter and game-bot contract
- **THEN** the LLM SHALL receive a result compatible with the previous embedded Minecraft bridge behavior

#### Scenario: Tool and streaming prompt content are equivalent
- **WHEN** tool-calling mode and streaming mode are run with equivalent state and configuration
- **THEN** both modes SHALL use equivalent compiled system prompt content
- **THEN** mode-specific code SHALL only control delivery mechanics, not prompt assembly semantics

#### Scenario: Realtime tool call keeps thinking disabled
- **WHEN** Anima v0.1 realtime roleplay triggers a tool call
- **THEN** the tool-calling provider request SHALL use the realtime DeepSeek policy
- **THEN** thinking mode SHALL remain disabled unless an explicit complex-reasoning route is selected

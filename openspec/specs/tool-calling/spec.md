## Purpose
Defines the accepted behavior and requirements for the tool-calling capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: ChatModel accepts TracingProxy-wrapped LLM services
The `create_chat_model_from_service` function SHALL unwrap dynamic proxies (such as TracingProxy) before creating the LLMChatModelAdapter, so that Pydantic's isinstance validation does not reject the proxy.

#### Scenario: TracingProxy is unwrapped before ChatModel creation
- **WHEN** `create_chat_model_from_service` is called with a `TracingProxy` wrapping an `LLMInterface`
- **THEN** the function SHALL detect the proxy and extract the underlying `LLMInterface` instance
- **THEN** `LLMChatModelAdapter` SHALL be created successfully with the raw `LLMInterface`

#### Scenario: Raw LLMInterface still works unchanged
- **WHEN** `create_chat_model_from_service` is called with a direct `LLMInterface` instance (no proxy)
- **THEN** the function SHALL pass it through unchanged
- **THEN** `LLMChatModelAdapter` SHALL be created successfully

### Requirement: Minecraft tools support runtime lifecycle
The Minecraft tool set SHALL support runtime start/stop via Socket.IO in addition to the existing boot-time `tools.yaml` config gate. When started at runtime, the bridge SHALL be initialized and tools registered without requiring a server restart.

#### Scenario: Runtime start registers tools
- **WHEN** `minecraft.start` is received and the bridge connects successfully
- **THEN** Minecraft tools (mine, place, move, attack, chat, status, set_goal) SHALL be available in the LangChain tool registry
- **THEN** the LLM SHALL be able to invoke them in subsequent conversation turns

#### Scenario: Runtime stop deregisters tools
- **WHEN** `minecraft.stop` is received and the bridge shuts down
- **THEN** Minecraft tools SHALL be removed from the LangChain tool registry
- **THEN** subsequent tool calls to Minecraft tools SHALL fail gracefully with a "Minecraft bot not connected" message

#### Scenario: Boot-time disabled but runtime started
- **WHEN** `tools.yaml` has `minecraft.enabled: false` (boot-time disabled)
- **THEN** `minecraft.start` SHALL still be able to start the bridge
- **THEN** the bridge SHALL bypass the boot-time config gate when invoked via the Socket.IO handler

### Requirement: Tool calling works end-to-end
When ChatModel creation succeeds with bound tools, the LLM node SHALL invoke tools during conversation. Tool-calling prompt delivery SHALL use the same compiled prompt contract as non-tool streaming delivery.

#### Scenario: LLM calls tool via ChatModel binding
- **WHEN** a user message triggers a tool call (e.g., "搜索今天的新闻")
- **THEN** the LLM node SHALL compile the final prompt through the prompt pipeline
- **THEN** the LLM node SHALL pass the compiled system prompt to the tool-calling provider call
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

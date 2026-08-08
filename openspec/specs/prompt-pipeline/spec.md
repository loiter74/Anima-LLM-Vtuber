## Purpose
Defines how system prompt contributors are compiled, ordered, delivered, and inspected before LLM calls.
## Requirements
### Requirement: Unified prompt compilation
The system SHALL provide a prompt pipeline that compiles all LLM system prompt contributors into a single `CompiledPrompt` before any LLM provider call.

#### Scenario: Compiles final system prompt once
- **WHEN** the LLM node is ready to call an LLM provider
- **THEN** the system SHALL call the prompt pipeline to produce one `CompiledPrompt`
- **THEN** the final system prompt text SHALL come from `CompiledPrompt.system_prompt`

#### Scenario: LLM node does not concatenate prompt sections
- **WHEN** persona, runtime personality, or memory context is present
- **THEN** the LLM node SHALL NOT manually concatenate those prompt fragments
- **THEN** the prompt pipeline SHALL own final prompt assembly

### Requirement: Prompt sections are structured
The prompt pipeline SHALL represent each prompt contributor as one or more structured prompt sections before rendering final prompt text.

#### Scenario: Prompt source emits structured section
- **WHEN** a prompt source contributes content
- **THEN** it SHALL return a section with a stable name, role, priority, content, and metadata
- **THEN** the assembler SHALL use those fields to render and describe the final prompt

#### Scenario: Empty section is skipped
- **WHEN** a prompt source has no content to contribute
- **THEN** the assembler SHALL omit that source from final prompt text
- **THEN** the final prompt SHALL NOT contain empty section separators

### Requirement: Prompt section ordering is deterministic
The prompt assembler SHALL render sections in a deterministic order that preserves instruction priority and keeps dynamic context separate from persistent persona content.

#### Scenario: Persona precedes runtime context
- **WHEN** persona and runtime personality sections are both present
- **THEN** the persona section SHALL appear before the runtime personality section

#### Scenario: Runtime context precedes memory context
- **WHEN** runtime personality and memory sections are both present
- **THEN** the runtime personality section SHALL appear before the memory section

### Requirement: Prompt delivery is mode-specific but content-equivalent
The system SHALL isolate prompt delivery mechanics from prompt assembly so tool-calling and streaming modes receive the same compiled prompt content.

#### Scenario: Tool mode receives compiled prompt
- **WHEN** tool-calling mode invokes `chat_with_tools`
- **THEN** it SHALL pass `CompiledPrompt.system_prompt` as the system prompt argument

#### Scenario: Streaming mode receives compiled prompt
- **WHEN** streaming mode invokes `chat_stream`
- **THEN** it SHALL use `CompiledPrompt.system_prompt` as the system prompt content

#### Scenario: Modes share compiled content
- **WHEN** the same state and configuration are used for tool-calling and streaming modes
- **THEN** both modes SHALL receive equivalent compiled system prompt text

### Requirement: Prompt debug metadata
The prompt pipeline SHALL expose metadata that allows developers to inspect prompt composition without requiring full prompt text logs.

#### Scenario: Metadata lists included sections
- **WHEN** a compiled prompt is produced
- **THEN** its metadata SHALL include the names of included sections
- **THEN** its metadata SHALL include the number of included sections

#### Scenario: Metadata records warnings
- **WHEN** a prompt source fails or omits expected content
- **THEN** the compiled prompt SHALL include a warning entry describing the source and failure category
- **THEN** prompt compilation SHALL continue when a safe fallback exists

### Requirement: Prompt pipeline failure containment
The prompt pipeline SHALL preserve the LLM call path when optional prompt contributors fail.

#### Scenario: Memory prompt source fails
- **WHEN** memory recall or memory section creation fails
- **THEN** the prompt pipeline SHALL compile a prompt without memory content
- **THEN** the LLM node SHALL still be able to call the LLM provider

#### Scenario: Base persona is missing
- **WHEN** no base persona prompt is available
- **THEN** the prompt pipeline SHALL compile the remaining available sections
- **THEN** the compiled prompt SHALL include a warning about the missing persona prompt

### Requirement: Live improvisation control layer
The prompt pipeline SHALL include one concise live response-control layer for realtime Anima chat replies without modifying the accepted persona config. Valid active scene guidance SHALL replace the generic improvisation section for that turn; otherwise the generic section SHALL remain the fallback.

#### Scenario: Generic live improvisation section is included
- **WHEN** the prompt pipeline compiles a realtime chat prompt without active scene guidance
- **THEN** the compiled prompt SHALL include the stable generic live improvisation section
- **THEN** the section metadata SHALL expose its stable section name

#### Scenario: Scene guidance replaces generic improvisation
- **WHEN** validated active `SceneGuidance` is present in turn metadata
- **THEN** the compiled prompt SHALL include a bounded scene-guidance section
- **THEN** the compiled prompt SHALL omit the generic live improvisation section

#### Scenario: Persona config remains the source of identity
- **WHEN** either live response-control section is added
- **THEN** the persona section SHALL remain included as the base identity source
- **THEN** the response-control section SHALL NOT require editing persona YAML content or override persona and safety constraints

#### Scenario: Generic improvisation sharpens reply style
- **WHEN** the generic live improvisation section is rendered
- **THEN** it SHALL instruct the model to produce short live-chat replies in Anima voice
- **THEN** it SHALL discourage customer-service phrasing, meta explanations, and rigid advice formatting

#### Scenario: Live response control precedes memory context
- **WHEN** a live response-control section and memory sections are both present
- **THEN** the live response-control section SHALL appear before memory context
- **THEN** memory context SHALL NOT become a conflicting style-setting instruction

### Requirement: Base persona prompt is derived from active config
The prompt pipeline SHALL derive the base persona prompt from the active runtime configuration when a service context is available, using state-provided prompt text only as a compatibility fallback.

#### Scenario: Service context config provides persona prompt
- **WHEN** the prompt pipeline compiles a prompt and `RunnableConfig.configurable.service_context.config` is available
- **THEN** the persona section SHALL be built from that active config's persona
- **THEN** the compiled prompt SHALL not depend on a separately precomputed orchestrator prompt string

#### Scenario: State prompt remains fallback for isolated callers
- **WHEN** the prompt pipeline compiles a prompt without an active service context config
- **THEN** it SHALL use `state["system_prompt"]` as the base persona prompt when present
- **THEN** it SHALL preserve the existing missing-persona warning behavior when no fallback exists

### Requirement: Live2D prompt is included consistently
The prompt pipeline SHALL include Live2D emotion instructions in the same base persona prompt path used by streaming and tool-calling modes.

#### Scenario: Live2D is enabled
- **WHEN** Live2D config is enabled and exposes valid emotions
- **THEN** the base persona prompt SHALL include the generated Live2D emotion instruction prompt
- **THEN** streaming and tool-calling LLM modes SHALL receive equivalent Live2D instructions

#### Scenario: Live2D prompt generation fails
- **WHEN** Live2D prompt generation fails during prompt compilation
- **THEN** the prompt pipeline SHALL continue compiling the persona prompt without Live2D instructions
- **THEN** the compiled prompt metadata SHALL include a warning for the omitted Live2D source

### Requirement: Runtime config version is reflected in compiled prompts
The prompt pipeline SHALL expose the runtime config version used to compile each prompt.

#### Scenario: Prompt compiled after reload
- **WHEN** runtime reload succeeds and a subsequent conversation turn compiles a prompt
- **THEN** the compiled prompt metadata SHALL include the new runtime config version
- **THEN** the persona prompt content SHALL come from the reloaded persona data

### Requirement: Scene guidance prompt validation and containment
The prompt pipeline SHALL consume scene guidance only after contract validation and SHALL contain source failures without blocking the LLM call.

#### Scenario: Malformed scene guidance metadata
- **WHEN** scene guidance metadata is malformed, expired, or schema-incompatible
- **THEN** the prompt pipeline SHALL omit it, include a safe warning, and retain generic improvisation behavior

#### Scenario: Scene guidance is rendered
- **WHEN** active guidance is valid
- **THEN** the rendered section SHALL contain only the current scene summary, response objective, scope, tone, selected technique, meme policy, and explicit avoid/must-address constraints
- **THEN** it SHALL NOT render raw analyzer output or retrieval candidate documents


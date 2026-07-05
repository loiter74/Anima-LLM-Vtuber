# memory-middleware Specification

## Purpose
TBD - created by archiving change supermemory-memory-enhancement. Update Purpose after archive.
## Requirements
### Requirement: 記憶中間件（MemoryMiddleware）

系統 SHALL 提供 `MemoryMiddleware` 元件，在 LLM 呼叫前後自動處理記憶。

`MemoryMiddleware` SHALL support a structured recall path for the prompt pipeline and SHALL preserve existing compatibility methods during migration.

For the new prompt pipeline path:

- the middleware SHALL retrieve memory through the configured memory system
- the middleware SHALL return structured recall context or prompt-ready memory data
- the middleware SHALL NOT assemble the final system prompt
- the prompt pipeline SHALL render memory content into the final compiled prompt

For the compatibility path:

- `before_llm_call(...)` MAY continue returning prompt text for existing callers and tests
- `_inject_into_prompt(...)` MAY remain as a compatibility helper
- new prompt pipeline code SHALL NOT use compatibility injection helpers as the source of final prompt assembly

`after_llm_call(...)` SHALL remain non-blocking and SHALL NOT prevent the main LLM flow from completing if memory storage is unavailable.

#### Scenario: LLM 呼叫前提供結構化記憶

- **WHEN** 使用者輸入對話文字，系統準備編譯 LLM prompt
- **THEN** `MemoryMiddleware` SHALL retrieve relevant memory context from the memory system
- **THEN** the middleware SHALL provide structured memory context to the prompt pipeline
- **THEN** the prompt pipeline SHALL render memory into the compiled system prompt

#### Scenario: Middleware does not own final prompt assembly

- **WHEN** the prompt pipeline is used for an LLM call
- **THEN** `MemoryMiddleware` SHALL NOT inject memory into the final system prompt directly
- **THEN** memory content SHALL appear only through a prompt pipeline memory section

#### Scenario: LLM 回應後自動儲存

- **WHEN** LLM 回覆完成
- **THEN** `after_llm_call` SHALL preserve its configured post-call memory handling behavior
- **THEN** memory post-processing failures SHALL NOT block the main response path

### Requirement: LangGraph 整合

中間件 SHALL integrate with LangGraph through the LLM node and prompt pipeline:

- before the LLM provider call, the prompt pipeline SHALL obtain memory context through the configured middleware or memory system
- after the LLM provider returns a response, the LLM node SHALL continue notifying memory middleware through `after_llm_call`
- middleware lookup SHALL continue using the existing LangGraph config/service context pattern
- memory failures SHALL be caught, logged, and converted into prompt pipeline warnings when safe fallback is possible

#### Scenario: 中間件不阻斷主流程

- **WHEN** memory retrieval or post-call memory handling raises an exception
- **THEN** the system SHALL catch the exception and record a warning
- **THEN** the LLM call main flow SHALL continue without memory content when a safe fallback exists

#### Scenario: Prompt pipeline receives memory metadata

- **WHEN** memory context is available
- **THEN** the prompt pipeline SHALL receive metadata sufficient to report memory section inclusion
- **THEN** the compiled prompt metadata SHALL identify that memory context was included

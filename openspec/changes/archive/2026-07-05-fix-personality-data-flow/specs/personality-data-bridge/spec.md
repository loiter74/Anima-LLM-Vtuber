## ADDED Requirements

### Requirement: personality_overlay injected into system prompt
When `state["metadata"]["personality_overlay"]` is non-empty, `llm_node` SHALL append it to the system prompt before passing to LLM inference.

#### Scenario: Overlay present in metadata
- **WHEN** personality_node produces `metadata.personality_overlay = "当前情绪：保持积极愉快的语气"`
- **THEN** the system prompt passed to LLM SHALL contain the overlay text

#### Scenario: No overlay in metadata
- **WHEN** `metadata.personality_overlay` is empty string or missing
- **THEN** the system prompt SHALL be unchanged (no empty string appended, no extra newlines)

### Requirement: knowledge boundaries passed to memory middleware
When `state["metadata"]` contains `character_known` or `character_unknown`, `llm_node._retrieve_memory_context()` SHALL pass them to `MemoryMiddleware.before_llm_call()`.

#### Scenario: Boundaries present in metadata
- **WHEN** personality_node produces `metadata.character_known=["编程","AI"]` and `metadata.character_unknown=["烹饪"]`
- **THEN** `MemoryMiddleware.before_llm_call()` SHALL receive `character_known=["编程","AI"]` and `character_unknown=["烹饪"]`

#### Scenario: No boundaries in metadata
- **WHEN** metadata does not contain character boundary keys
- **THEN** `MemoryMiddleware.before_llm_call()` SHALL receive `character_known=None` and `character_unknown=None` (current default behavior preserved)

### Requirement: MBTI dimensions passed to memory middleware
When `state["metadata"]` contains MBTI dimension values, `llm_node._retrieve_memory_context()` SHALL pass them to `MemoryMiddleware.before_llm_call()`.

#### Scenario: MBTI dimensions present in metadata
- **WHEN** personality_node produces `metadata.mbti_ei=20, mbti_sn=65, mbti_tf=80, mbti_jp=73`
- **THEN** `MemoryMiddleware.before_llm_call()` SHALL receive `mbti_ei=20, mbti_sn=65, mbti_tf=80, mbti_jp=73`

#### Scenario: No MBTI in metadata
- **WHEN** metadata does not contain MBTI keys
- **THEN** `MemoryMiddleware.before_llm_call()` SHALL receive `mbti_ei=50, mbti_sn=50, mbti_tf=50, mbti_jp=50` (current default behavior preserved)

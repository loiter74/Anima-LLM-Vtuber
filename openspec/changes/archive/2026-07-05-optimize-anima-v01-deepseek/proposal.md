## Why

Anima v0.1 introduces a short, roleplay-focused persona, but the runtime path still needs explicit DeepSeek V4 model policy, thinking-mode control, drift correction, and repeatable dialogue evaluation. Without those controls, realtime livestream replies can silently use the wrong reasoning mode, become assistant-like, or pass manual review without objective roleplay criteria.

## What Changes

- Add explicit DeepSeek runtime policy for Anima v0.1:
  - realtime roleplay uses `deepseek-v4-flash` with thinking disabled
  - complex reasoning uses `deepseek-v4-pro` with thinking enabled only when selected
- Add DeepSeek `thinking` / request-extra passthrough requirements for OpenAI-compatible provider calls.
- Add an Anima roleplay guard that detects assistant-flavor drift and injects a one-turn correction section.
- Add a dialogue evaluation capability with concrete input cases and scoring dimensions for Anima v0.1.
- Add prompt/history pressure constraints so persona/runtime guard sections remain stronger than memory and long chat history.
- Extend tool-calling and existing LLM evaluation requirements so DeepSeek thinking mode and roleplay quality are testable.

## Capabilities

### New Capabilities
- `deepseek-runtime-policy`: Defines DeepSeek V4 model selection, thinking-mode configuration, request-extra passthrough, and runtime routing for Anima v0.1.
- `anima-roleplay-guard`: Defines assistant-flavor drift detection and one-turn correction injection for Anima v0.1.
- `anima-roleplay-evaluation`: Defines dialogue test cases and scoring criteria used to judge whether Anima v0.1 stays in character.

### Modified Capabilities
- `prompt-pipeline`: Runtime roleplay guard and memory/history pressure rules add new prompt-section ordering and one-turn correction behavior.
- `tool-calling`: Tool-calling must preserve the selected DeepSeek thinking mode and request extras while using the compiled prompt.
- `llm-evaluation`: Existing LLM evaluation must support roleplay quality evaluation in addition to semantic similarity.

## Impact

- Affected backend modules:
  - `src/animetta/config/providers/llm/deepseek.py`
  - `src/animetta/services/llm/openai_llm.py`
  - `src/animetta/services/llm/stream_handler.py`
  - `src/animetta/services/llm/tool_handler.py`
  - prompt pipeline / graph integration modules used for runtime correction sections
- Affected config:
  - DeepSeek service YAML examples
  - Anima v0.1 development/runtime config
- Affected evaluations:
  - new Anima v0.1 dialogue cases and scoring rules
  - optional live eval gated by `DEEPSEEK_API_KEY`
- No persona YAML schema change is intended.

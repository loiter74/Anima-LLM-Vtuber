## Why

The current Anima v0.1 runtime work is partially implemented but has correctness gaps: roleplay guard and evaluation fixtures still reference an old character, invalid DeepSeek thinking modes are accepted, and runtime policy / drift correction need explicit tests proving they are wired into the conversation path. These issues can make tests pass while validating the wrong roleplay behavior.

## What Changes

- Fix Anima roleplay guard text so correction sections reference Anima, the cyber tavern, travelers, and Summoner X instead of the old character.
- Fix Anima dialogue evaluation fixtures and passing examples so they validate Anima v0.1 rather than unrelated character markers.
- Enforce DeepSeek thinking mode validation so only `enabled` and `disabled` are accepted.
- Add TDD coverage for DeepSeek realtime and complex runtime policy behavior at the LLM call boundary.
- Add TDD coverage for assistant-flavor drift detection producing a one-turn Anima correction section in prompt compilation.
- Add repository search / regression checks ensuring roleplay guard and eval files do not contain the old character markers.

## Capabilities

### New Capabilities
- `anima-v01-runtime-regression`: Regression contract for preventing old-character marker leakage in Anima v0.1 roleplay guard, dialogue evaluation, and prompt correction behavior.
- `anima-roleplay-guard`: Defines Anima-specific assistant-flavor drift detection and one-turn correction behavior.
- `anima-roleplay-evaluation`: Defines Anima v0.1 dialogue cases and deterministic scoring criteria.
- `deepseek-runtime-policy`: Defines DeepSeek thinking-mode validation and runtime model routing for Anima v0.1.

### Modified Capabilities
- `prompt-pipeline`: Prompt compilation must include Anima correction sections only when roleplay correction metadata is present and keep them ahead of memory.

## Impact

- Affected source:
  - `src/animetta/orchestration/prompting/roleplay_guard.py`
  - `src/animetta/orchestration/prompting/context.py`
  - `src/animetta/orchestration/prompting/sources.py`
  - `src/animetta/config/providers/llm/deepseek.py`
  - DeepSeek runtime policy integration point if currently not wired into LLM calls
- Affected tests:
  - `tests/orchestration/graph/test_roleplay_guard.py`
  - `tests/eval/test_anima_roleplay_eval.py`
  - `tests/eval/test_anima_eval_scoring.py`
  - `tests/config/test_deepseek_config.py`
  - LLM node / provider boundary tests for runtime policy usage
- No persona YAML schema change is intended.

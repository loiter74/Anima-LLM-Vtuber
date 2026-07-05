## 1. Roleplay Guard TDD Fix

- [x] 1.1 RED: Add a test asserting `CORRECTION_SECTION` contains Anima-specific markers such as `Anima`, `赛博酒馆`, `旅人`, or `召唤者 X`.
- [x] 1.2 RED: Add a test asserting `CORRECTION_SECTION` does not contain `久遠寺`, `有珠`, or `魔女`.
- [x] 1.3 Verify the new guard tests fail for the expected reason before changing production code.
- [x] 1.4 GREEN: Replace `CORRECTION_SECTION` with Anima v0.1-specific correction text.
- [x] 1.5 Verify `tests/orchestration/graph/test_roleplay_guard.py` passes.

## 2. Anima Evaluation Fixture TDD Fix

- [x] 2.1 RED: Add a test asserting all Anima roleplay evaluation cases and passing examples contain no `久遠寺`, `有珠`, or `魔女`.
- [x] 2.2 RED: Add a test asserting the `identity_question` case prefers Anima v0.1 markers such as `Anima`, `赛博酒馆`, or `旅人`.
- [x] 2.3 Verify the new evaluation tests fail for the expected reason before changing fixtures.
- [x] 2.4 GREEN: Replace old-character markers in evaluation fixtures and passing examples with Anima v0.1 cyber tavern markers.
- [x] 2.5 Verify `tests/eval/test_anima_roleplay_eval.py` and `tests/eval/test_anima_eval_scoring.py` pass.

## 3. DeepSeek Thinking Validation TDD Fix

- [x] 3.1 RED: Add a test asserting `DeepSeekLLMConfig(api_key="test", thinking="banana")` raises a validation error.
- [x] 3.2 Verify the new config test fails for the expected reason before changing provider config.
- [x] 3.3 GREEN: Change DeepSeek thinking config to `Literal["enabled", "disabled"]` or add an equivalent Pydantic validator.
- [x] 3.4 Verify existing enabled/disabled config tests and extra-body passthrough tests still pass.

## 4. Runtime Policy Boundary Tests

- [x] 4.1 RED: Add a focused test proving realtime/danmaku policy produces `deepseek-v4-flash` with thinking disabled at the provider config or LLM call boundary.
- [x] 4.2 RED: Add a focused test proving explicit complex policy produces `deepseek-v4-pro` with thinking enabled at the provider config or LLM call boundary.
- [x] 4.3 Verify the boundary tests fail if current policy helper is not actually wired to the call path.
- [x] 4.4 GREEN: Wire runtime policy into the narrowest appropriate call boundary if tests prove it is missing.
- [x] 4.5 Verify policy metadata records mode/model/thinking without logging full prompt text if metadata is part of the implementation path.

## 5. Drift-to-Correction Lifecycle Tests

- [x] 5.1 RED: Add a test proving assistant-flavor output such as `作为 AI` produces Anima roleplay correction metadata for the next prompt compilation.
- [x] 5.2 RED: Add a test proving correction metadata is absent on the following turn unless new drift is detected.
- [x] 5.3 Verify lifecycle tests fail for the expected reason before changing graph/prompt code.
- [x] 5.4 GREEN: Implement the smallest safe wiring from drift detection to one-turn `metadata["roleplay_correction"]` if missing.
- [x] 5.5 Verify correction sections appear before memory and are not persisted into persona config or memory.

## 6. Regression Search and Focused Verification

- [x] 6.1 Add or run a focused regression check over active Anima guard/eval files for forbidden old-character markers.
- [x] 6.2 Run `PYTHONPATH=src python -m pytest -o addopts='' tests/orchestration/graph/test_roleplay_guard.py -q`.
- [x] 6.3 Run `PYTHONPATH=src python -m pytest -o addopts='' tests/eval/test_anima_roleplay_eval.py tests/eval/test_anima_eval_scoring.py -q`.
- [x] 6.4 Run `PYTHONPATH=src python -m pytest -o addopts='' tests/config/test_deepseek_config.py tests/services/llm/test_deepseek_policy.py -q`.
- [x] 6.5 Run any new LLM boundary / prompt lifecycle tests added for this fix.
- [x] 6.6 Run `ruff check` for changed source and test files.
- [x] 6.7 If runtime service code is changed and the implementation is declared ready, complete the project Docker startup protocol before final completion.

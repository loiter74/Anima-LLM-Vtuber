## 1. Tests (Write First — Red Phase)

- [x] 1.1 Create `tests/test_llm_node_personality_bridge.py` with test fixtures (mock service_context, mock middleware, sample state with personality metadata)
- [x] 1.2 Write test: `test_overlay_appended_to_system_prompt` — state has `metadata.personality_overlay="当前情绪：保持积极愉快的语气"`, verify final system prompt contains overlay text
- [x] 1.3 Write test: `test_no_overlay_when_empty` — state has `metadata.personality_overlay=""`, verify system prompt unchanged
- [x] 1.4 Write test: `test_no_overlay_when_metadata_missing` — state has no metadata key, verify system prompt unchanged
- [x] 1.5 Write test: `test_character_boundaries_passed_to_middleware` — state has `metadata.character_known=["编程"]` and `metadata.character_unknown=["烹饪"]`, verify middleware receives them
- [x] 1.6 Write test: `test_default_when_no_boundaries` — state has no character metadata, verify middleware receives `None` defaults
- [x] 1.7 Write test: `test_mbti_dimensions_passed_to_middleware` — state has `metadata.mbti_ei=20, mbti_sn=65, mbti_tf=80, mbti_jp=73`, verify middleware receives them
- [x] 1.8 Write test: `test_default_mbti_when_no_metadata` — state has no mbti metadata, verify middleware receives `50/50/50/50`
- [x] 1.9 Run tests — 4 middleware tests FAIL (red confirmed), 3 overlay contract tests pass

## 2. Fix: personality_overlay → system_prompt (Green Phase)

- [x] 2.1 In `llm_node.py` `_llm_with_tools()`: read `personality_overlay` from `state["metadata"]`, append to `system_prompt` when non-empty
- [x] 2.2 In `llm_node.py` `_llm_without_tools()`: same overlay injection logic
- [x] 2.3 Run tests 1.2–1.4 — verify 3 overlay tests pass

## 3. Fix: character/MBTI → memory middleware (Green Phase)

- [x] 3.1 Update `_retrieve_memory_context()` signature to accept `character_known`, `character_unknown`, `mbti_ei/sn/tf/jp` parameters
- [x] 3.2 Pass the new parameters through to `middleware.before_llm_call()`
- [x] 3.3 In both `_llm_with_tools()` and `_llm_without_tools()`: extract character/MBTI values from `state["metadata"]` and pass to `_retrieve_memory_context()`
- [x] 3.4 Run tests 1.5–1.8 — verify 4 middleware tests pass

## 4. Verify & Clean Up

- [x] 4.1 Run full test suite — all 7 new tests green, no regressions (pre-existing import errors in other files unchanged)
- [x] 4.2 Log bug to `.wolf/buglog.json`
- [x] 4.3 Update `.wolf/anatomy.md` if new test file added

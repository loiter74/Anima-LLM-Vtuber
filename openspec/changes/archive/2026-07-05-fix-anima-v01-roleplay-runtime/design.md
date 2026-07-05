## Context

The current Anima v0.1 runtime work has implementation artifacts in the tree, but review found several mismatches between passing tests and intended behavior:

- `roleplay_guard.CORRECTION_SECTION` still references an old character instead of Anima.
- Anima roleplay evaluation cases still reward old-character identity markers.
- `DeepSeekLLMConfig` accepts unsupported thinking mode values.
- Runtime policy and drift correction need tests that prove they affect the actual prompt / LLM call boundary, not only isolated helper functions.

This change is a corrective pass. It should not expand the architecture or rewrite the prompt pipeline. The work must follow TDD: write a failing test for each observed defect, verify the failure, then make the smallest production change that passes.

## Goals / Non-Goals

**Goals:**

- Remove old-character leakage from Anima roleplay guard and Anima evaluation fixtures.
- Make invalid DeepSeek thinking modes fail validation.
- Prove Anima correction sections are Anima-specific, one-turn, and ordered before memory.
- Prove realtime DeepSeek policy keeps Flash + thinking disabled and complex policy keeps Pro + thinking enabled at the call boundary.
- Add a regression search/test that prevents old-character markers from returning to Anima guard/eval files.

**Non-Goals:**

- Do not change `config/personas/anima.v0.1.yaml` unless a test proves the persona config itself is wrong.
- Do not change the persona YAML schema.
- Do not implement live DeepSeek API evaluation in this fix.
- Do not redesign prompt pipeline section types or priorities beyond what is required for the bug fixes.
- Do not perform broad refactors of LLM providers.

## Decisions

### Decision 1: Treat old-character leakage as a regression class

Add tests that fail if Anima-specific guard/eval files contain `久遠寺`, `有珠`, or `魔女`. This catches both visible correction text and hidden fixture criteria.

Alternative considered: only manually inspect strings. Rejected because the current issue occurred despite tests passing.

### Decision 2: Keep correction text static but Anima-specific

The correction text should remain a simple constant for this fix, but it must reference Anima, the cyber tavern, travelers, and Summoner X. A dynamic persona-derived correction can be designed later if multiple active roleplay personas need this guard.

Alternative considered: generate correction text from persona YAML. Rejected for this fix because it adds complexity and can make tests less precise.

### Decision 3: Use Pydantic validation for DeepSeek thinking mode

The config should reject unsupported values at model validation time, using `Literal["enabled", "disabled"]` or an equivalent validator.

Alternative considered: silently map unknown values to disabled. Rejected because silent fallback hides deployment configuration errors.

### Decision 4: Verify runtime behavior at the narrowest useful boundary

Do not start with Docker or live API tests. First prove request kwargs and prompt compilation are correct with unit tests / focused integration tests. Docker startup remains required if implementation changes runtime service behavior and the apply phase declares the service ready.

Alternative considered: only use live eval. Rejected because live eval is slow, flaky, and requires credentials.

## Risks / Trade-offs

- Tests fail due to stale OpenSpec artifacts containing old strings -> Mitigation: scope marker-regression tests to active runtime/eval source files, not archived docs.
- Strict thinking validation breaks existing configs with old shorthand -> Mitigation: allow only the currently intended string values and update config examples in the same change.
- Runtime policy call-boundary test is hard to write because LLM node setup is coupled -> Mitigation: test provider construction/request kwargs first, then add the smallest graph-level test possible.
- Correction metadata lifecycle is ambiguous -> Mitigation: define one-turn behavior as present only when metadata is present, and add separate follow-up if automatic metadata production is not wired.

## Migration Plan

1. Add failing tests for Anima correction content and no old-character markers.
2. Replace correction text with Anima-specific text.
3. Add failing tests for Anima evaluation identity cases and no old-character markers.
4. Fix eval fixtures and passing examples.
5. Add failing test for invalid DeepSeek thinking value.
6. Add Pydantic validation and verify DeepSeek extra-body tests still pass.
7. Add focused prompt pipeline / LLM boundary tests for correction ordering and DeepSeek policy.
8. Run targeted tests and lint.

Rollback strategy: revert the touched guard/eval/config files. Because this change is narrow and does not change external APIs beyond rejecting invalid config, rollback is localized.

## Open Questions

- Whether automatic drift detection should happen in `output_node`, `llm_node`, or a dedicated graph node is still a larger design question. This fix should only add tests that expose the current gap and implement the smallest safe wiring if feasible.

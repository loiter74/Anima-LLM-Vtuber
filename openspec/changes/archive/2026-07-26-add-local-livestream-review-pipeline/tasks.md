## 1. Local Review Foundation

- [x] 1.1 Add failing unit tests for review scene resolution, canonical event order, timer cleanup, and unknown-scene fallback
- [x] 1.2 Implement the typed in-memory review socket and deterministic `empty` and `baseline` scene catalog
- [x] 1.3 Add failing entrypoint tests proving `review=1` and legacy `demo=1` never construct the real Socket.IO client
- [x] 1.4 Integrate review-mode selection into the standalone live entry while preserving production behavior
- [x] 1.5 Use fresh Playwright and OBS captures to present `empty` and `baseline`, then record the human pass/adjust/redo verdict
  - Human verdicts: `empty` pass (attempt 4); `baseline` pass (attempt 1)

## 2. Progressive Review Scenes

- [x] 2.1 After baseline passes, add failing tests and fixtures for `text-boundaries`, then present and gate the scene
  - Human verdict: `text-boundaries` pass (attempt 3); OBS source URL synchronized to the matching scene
- [x] 2.2 After text boundaries pass, add failing tests and fixtures for `sparse` and `burst`, then present and gate both scenes
  - Human verdict: `sparse` pass (`aligned-no-collapse-1`); panel top aligned with status rail and collapse affordance removed
  - Human verdict: `burst` adjust (`burst-1`); constrain the panel above Live2D and hide the scrollbar, then rerun
  - Human verdict: `burst` pass (`burst-2-compact`); panel constrained above Live2D, scrollbar hidden, auto-scroll preserved
- [x] 2.3 After traffic scenes pass, add failing tests and rendering for gift/super-chat variants in `special`, then present and gate the scene
  - Human verdict: `special` pass (`special-sync-1`); fixed gift/super-chat fixtures preserved and OBS URL re-verified against the Chrome scene before approval
- [x] 2.4 After special passes, add failing tests and fixtures for `recovery`, then present and gate the scene
  - Human verdict: `recovery` pass (`recovery-4`); deterministic 0/4/8/12-second live, disconnect, reconnecting, and recovered sequence, with matching Chrome and OBS scene URLs
- [x] 2.5 After technical scenes pass, add and gate the final `overall` composition scene
  - Human verdict: `overall` pass (`overall-1`); Chrome and OBS showed the same four-message composition with one gift and one super-chat, the top-right panel remained clear of Live2D, and no collapse affordance or scrollbar was visible

## 3. Interactive Playwright Runner

- [x] 3.1 Add failing tests for verdict parsing, append-only attempt evidence, workflow fingerprints, and stable-round reset/count behavior
- [x] 3.2 Implement the local review ledger and per-attempt evidence schema under `artifacts/live-review/<run-id>/`
- [x] 3.3 Add failing runner tests for fresh 1080 × 1920 contexts, semantic readiness assertions, trace/screenshot capture, and error collection
- [x] 3.4 Implement the headed Playwright runner with pass/adjust/redo gates and optional OBS screenshot attachment
- [x] 3.5 Add `pnpm live:review`, bounded preflight, deterministic cleanup, and operator-facing scene instructions
  - Verification: 8 Node runner/ledger tests pass; a fresh headed `overall` capture produced a 1080 × 1920 screenshot and trace with zero console, page, or request failures

## 4. Verification and Flow Freeze

- [x] 4.1 Run focused Vitest suites, frontend typecheck/build, and impact-selected repository verification
  - Verification: live Vitest 36/36, runner/ledger Node tests 8/8, typecheck and production build passed; affected quality plan `586641bd4124` passed after 4622 backend tests and all selected frontend/repository gates
- [x] 4.2 Execute the full Docker startup protocol through a dedicated sub-agent and confirm health, frontend access, and clean logs
- [x] 4.3 Complete one all-pass human review round with fresh Playwright and OBS evidence for every frozen scene
  - Round 1: `2026-07-24T17-09-27Z-2262301a`; all eight frozen scenes passed with fresh Chrome screenshots, Playwright traces, and OBS screenshots
- [x] 4.4 Complete a second unchanged all-pass round and verify the stable-round count reaches two
  - Round 2: `2026-07-25T11-01-06Z-f6a921cb`; all eight scenes passed unchanged on attempt 1 and `summary.json` reports `stable_rounds: 2`
- [x] 4.5 Validate OpenSpec artifacts, evidence completeness, cleanup behavior, and the final `pnpm live:review` workflow
  - OpenSpec strict validation passed; live Vitest 36/36, runner/ledger Node tests 9/9, typecheck, lint, and production build passed
  - Both frozen runs contain eight attempt JSON files plus all eight Chrome screenshots, Playwright traces, and OBS screenshots; early attempts retain null OBS attachment fields rather than rewriting append-only history, while their deterministic OBS files remain present
  - Impact plan `ef738c75c588` executed all selected groups; only unrelated pre-existing/user-owned `scripts/collect_danmaku*.py` lint and repository Python-format findings failed

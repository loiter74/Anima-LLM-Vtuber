## 1. Semantic Contract

- [x] 1.1 Add failing backend tests for valid, invalid, duplicate, missing, and legacy performance markers plus text stripping and compatible emotion/VAD mapping
- [x] 1.2 Implement versioned performance plan types and the pure avatar-domain parser until the focused backend tests pass
- [x] 1.3 Add failing prompt-pipeline tests for one leading bounded marker, calm-first guidance, and no additional LLM call
- [x] 1.4 Implement the performance prompt source and integrate parsed plans into AgentState and emotion orchestration

## 2. Audio Delivery

- [x] 2.1 Add failing backend contract tests for semantic performance on streaming and complete audio, no raw model controls, and calm behavior without audio
- [x] 2.2 Attach the validated plan to audio-start payloads, retain legacy expression delivery, and remove response-path `Idle[index]` emission
- [x] 2.3 Add safe low-cardinality plan observations and tests without content, raw markers, or paths

## 3. Hiyori Rendering

- [x] 3.1 Add failing model contract tests for sole `m01` idle, valid Hiyori profile parameters, and deterministic parameter mapping
- [x] 3.2 Restrict Hiyori idle to `m01`, correct eyebrow IDs, and remove random mapper variance without changing TapBody
- [x] 3.3 Add failing Vitest coverage for calm/armed/speaking/settling transitions, stale task gating, one accent, bounds, parameter ownership, interruption, and idempotent teardown
- [x] 3.4 Implement the Hiyori semantic profile and Live2DPerformanceController with 250 ms activation, 350 ms settling, late-frame overlay, and lip sync last
- [x] 3.5 Integrate optional performance fields into streaming and complete audio playback while preserving trusted manual actions

## 4. Review and Verification

- [x] 4.1 Add an isolated `live2d-performance` review feature for seven bases and five accents without modifying `text-boundaries` or `sparse`
- [x] 4.2 Run Python 3.13 preflight, focused/full Pytest and Vitest, frontend typecheck/build, OpenSpec strict validation, quality validation, and affected tests
- [x] 4.3 Capture fresh QA/Playwright/OBS evidence for calm idle, audio alignment, lip sync ownership, accent count, interruption, and calm recovery
- [x] 4.4 Run the complete Docker startup protocol in a sub-agent and verify persistent 8766/8767 identities, HTTP readiness, frontend access, and clean Compose logs
  - Prior block (2026-07-27): platform budget approval denied `anima-up` (GPU/Qwen path) twice; window would have reopened 2026-08-02 04:52 local.
  - Resolution (2026-07-27): used the GPU-free CPU-mode path `docker compose -f docker-compose.cpu.yml up -d --build` (the explicit no-GPU branch documented in AGENTS.md). This is a separate Compose project from Qwen, so Qwen could not be recreated — the persistent-8766 contract holds structurally, not just by `--no-recreate`.
  - Sub-agent evidence: `/health` → HTTP 200 `{"status":"ok","service":"anima"}` on attempt 2/24; frontend `/` → HTTP 200 on attempt 1/12; Qwen 8766 identity unchanged (`8a81c1d77226`, healthy) before and after; both Compose project logs clean (no Traceback/ERROR).
  - Independently re-verified by the parent agent after the sub-agent reported: `/health` 200, `/` 200, Qwen still `8a81c1d77226` Up 3 days (healthy), Animetta app `81c797e05fee` Up healthy.

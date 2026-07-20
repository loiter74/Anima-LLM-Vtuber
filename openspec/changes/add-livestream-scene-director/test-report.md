# Livestream Scene Director Test Report

**Date:** 2026-07-21
**Result:** Passed
**Runtime boundary:** `selftest` validates production DeepSeek/MiMo behavior with persistent local Qwen/Alice TTS. It is not evidence for the production DashScope TTS provider.

## Requirement coverage

| Requirement | Evidence | Result |
|---|---|---|
| History-neutral scene reflection | Gateway tests prove `chat_messages()` leaves shared main-LLM history unchanged and never falls back to `chat()` | Passed |
| All live events observed | Bilibili/session tests cover admitted and non-admitted danmaku plus host-reply feedback | Passed |
| Generation/revision isolation | Runtime and reducer tests cover room reset, stale events, stale patches, and single-writer revision checks | Passed |
| Single-flight and degradation | Runtime tests cover coalescing, rate budget, timeout, invalid JSON/schema, unavailable provider, stale cache, and empty retrieval | Passed |
| Guidance integration | Prompt tests cover validated guidance injection, improvisation fallback, malformed containment, and active/shadow/off modes | Passed |
| Humor/meme ownership | Graph tests prove scene-guided turns bypass model Humor Rewrite while explicit manual meme commands remain available | Passed |
| Local-Qwen self-test isolation | Manifest/Compose/lifecycle tests prove `selftest` selects `qwen-alice` while production remains `dashscope-seren` | Passed |
| Production-like self-test readiness | Self-test requires model warmup, DeepSeek connectivity, exact provider identity, frontend assets, and fail-closed pooled engines | Passed |

## Automated verification

- Python interpreter preflight: Python 3.13.14.
- Focused scene/config/deployment/lifecycle suite: 216 passed.
- Final readiness/service-pool/stats regression suite: 128 passed.
- Final Playwright harness contracts: 2 passed after red-first reproduction.
- Ruff: source/tests/scripts/tooling check passed; formatting passed.
- Mypy: 425 source files passed.
- Quality catalog: 34 groups, 18 components; manifest hash `5d25b704c237e9cca9ceb70a51a34e6079c914f88cb25b1e921e8ce97dfa42ad`.
- Final affected quality plan: `317b0679e7ea28ddf2c05858b7f74ade26775df3ec6e07864b50b54cf053bd5b`, passed in 313.46 seconds.
- Final backend full suite: 4622 passed, 33 skipped, 2 xfailed; total coverage 78.50%.
- OpenSpec strict validation: passed.
- Read-only code review after fixes: no Critical or Important findings.

## Replay and latency evidence

- Anonymous replay: 90 live events produced 3 scene-model reflections.
- Call reduction versus per-event analysis: 96.67%, exceeding the 70% target.
- Replay reached `cooldown`, moved the tracked meme to `overused`, selected `avoid`, and constrained the reply to 2 sentences / 180 characters without topic switching.
- Cached guidance benchmark observed approximately 0.0007 ms P95 in the focused run; the automated acceptance threshold is P95 below 50 ms.

## Docker self-test evidence

- Lifecycle entrypoint: `py -3.13 scripts/runtime_lifecycle.py anima-selftest-up`.
- Qwen remained persistent across all Animetta down/build/up cycles:
  - container ID prefix: `8a81c1d7`
  - StartedAt: `2026-07-20T16:12:17.799092324Z`
  - state: healthy
- Final Animetta image prefix: `c9eae12e`; container state: running / healthy.
- `GET /health`: HTTP 200, `status=ok`.
- `GET /ready`: HTTP 200, `ready=true`, profile `selftest`.
- Resolved LLM: `deepseek-v4-flash`.
- Resolved TTS: `qwen-alice / qwen3 / Qwen/Qwen3-TTS-12Hz-0.6B-Base / alice`.
- Frontend: HTTP 200.
- Final log window from `2026-07-20T16:59:17.4858083Z`: default Compose 444 lines and Qwen Compose 0 new lines; Traceback/ERROR-level count was zero for both projects.

One warning-level `Provider error` message was emitted when a concurrent background inspection reached the single-flight Qwen worker while the browser acceptance turn owned it. The primary acceptance turn completed; the structured log level was WARNING, not ERROR.

## Fresh browser evidence

- Release-mode Playwright completed in 62.5 seconds against the final rebuilt service.
- Provider rows were exact for DeepSeek and Qwen/Alice.
- Chinese assistant turn completed with no internal prompt markers.
- Audio evidence: 2 play calls (silent gesture unlock plus Alice audio), 2 resolved, 0 rejected, 1 completed, 0 media errors.
- Console errors, page errors, request failures, and HTTP errors were all empty.
- Evidence: [`artifacts/playwright/scene-analysis-selftest-20260721-010156/evidence.json`](../../../artifacts/playwright/scene-analysis-selftest-20260721-010156/evidence.json)
- Screenshots: [`provider-rows.png`](../../../artifacts/playwright/scene-analysis-selftest-20260721-010156/provider-rows.png), [`chinese-alice-turn.png`](../../../artifacts/playwright/scene-analysis-selftest-20260721-010156/chinese-alice-turn.png)

## Residual risks and rollout boundary

- The first deployment remains `shadow`; switching to `active` should follow anonymous replay and live-room observation.
- This self-test does not validate DashScope credentials, latency, availability, or Seren voice behavior in the production profile.
- Local Qwen is single-flight. Concurrent inspection or user TTS can receive a retryable busy degradation; scheduling/queueing is a separate operational improvement.
- V1 state is current-live only; cross-live stream/community memory remains out of scope.

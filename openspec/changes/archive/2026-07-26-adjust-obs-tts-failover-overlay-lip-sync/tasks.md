## 1. Test-first contracts

- [x] 1.1 Replace the top-right notification positioning assertion with a failing central upper safe-area assertion, including animation centering.
- [x] 1.2 Add failing mouth-driver tests that prove interpolated 60 ms sampling, visible low speech frames, deterministic out-of-range behavior, and zero reset on pause/end/stop.
- [x] 1.3 Update the OBS review geometry assertion to reject intersection with the danmaku panel and Live2D face safe region.

## 2. Focused implementation

- [x] 2.1 Center the compact failover notification at the approved upper safe-area offset while preserving its existing dimensions, tokens, responsive bounds, and vertical entrance motion.
- [x] 2.2 Interpolate the review-only envelope at a named 60 ms lead and lift low non-zero speech values while retaining bounded smoothing and post-motion mouth application.
- [x] 2.3 Preserve the existing audio lifecycle, report privacy, single-output OBS monitoring, and untouched `LIVE_REVIEW_SCENES` fixtures.
- [x] 2.4 Move review audio sampling into the Live2D post-motion model-update callback and disable the competing review RAF loop.

## 3. Automated verification

- [x] 3.1 Run the focused notification, lip-sync, and review-plugin Vitest suites through the green phase.
- [x] 3.2 Run Python 3.13 preflight, frontend typecheck, full Vitest, production build, OpenSpec strict validation, `quality validate`, and `test-affected`.
- [x] 3.3 Confirm `text-boundaries` and `sparse` names, messages, and exact assertions remain unchanged.

## 4. Fresh OBS acceptance

- [x] 4.1 Capture a fresh Playwright/OBS `tts-failover` run proving the notification no longer overlaps danmaku and the mouth target is applied.
- [x] 4.2 Replay the real Chinese fallback sentence for human comparison and confirm the stable same-frame 60 ms lead and low-speech visibility.
- [x] 4.3 Run the Docker startup protocol through a sub-agent, proving Qwen 8766 and host 8767 identities remain unchanged and both Compose logs contain no Traceback/ERROR.
- [x] 4.4 Restore the original OBS scene, Browser Source settings, audio monitoring state, and temporary review resources after success, failure, or interruption.

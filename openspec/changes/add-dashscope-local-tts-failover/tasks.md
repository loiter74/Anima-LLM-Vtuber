## 1. Host streaming contract

- [x] 1.1 Add failing contract tests for authenticated PCM streaming, exact identity, WAV compatibility, busy handling, and cancellation-safe capacity.
- [x] 1.2 Add the host GGUF engine adapter and extend the ASGI speech service with chunked PCM streaming.
- [x] 1.3 Add a supported per-task PCM chunk subscription to the pinned D-drive decoder runtime and copy/hash-verify the approved voice reference.

## 2. Composite provider

- [x] 2.1 Add failing tests for FailoverTTS preload, retry categories, first-chunk binding, circuit cooldown, single-flight recovery, cancellation, and close ownership.
- [x] 2.2 Add FailoverTTS configuration and provider registration with exact primary/fallback child schemas.
- [x] 2.3 Implement streaming and non-streaming failover, bounded retry, breaker state, half-open recovery, and actual-backend metadata.
- [x] 2.4 Preserve and test DashScope billing classification as a non-retryable provider error.

## 3. Readiness and observability

- [x] 3.1 Add failing readiness tests for primary-only, fallback-only, both-ready, neither-ready, and child identity mismatch.
- [x] 3.2 Implement cached composite readiness, degraded state, active backend, child status, circuit status, and safe identity resolution.
- [x] 3.3 Add bounded backend/failover/circuit/first-audio/RTF observation fields and Prometheus projections.

## 4. Configuration and lifecycle

- [x] 4.1 Select the composite provider in production and add authenticated host URL/token environment wiring without changing port 8766.
- [x] 4.2 Add failing lifecycle tests for idempotent host start/status/stop, best-effort anima-up, persistent anima-down, and PID validation.
- [x] 4.3 Implement hidden Windows host process management with D-drive PID/log files and readiness preflight.

## 5. Verification

- [x] 5.1 Run focused Python 3.13 unit, contract, readiness, lifecycle, and integration tests.
- [x] 5.2 Run OpenSpec validation, `make quality-validate`, and `make test-affected` without modifying unrelated danmaku fixtures.
- [x] 5.3 Run the warm real-host benchmark and verify PCM format, first chunk <= 0.75 seconds, and RTF <= 0.35.
- [x] 5.4 Capture fresh QA/Playwright evidence and execute the sub-agent Docker startup protocol while proving the existing Qwen container identity is unchanged.

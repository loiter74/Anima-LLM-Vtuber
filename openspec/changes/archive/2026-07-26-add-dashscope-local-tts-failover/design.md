## Context

Production selects one DashScope realtime TTS instance. ServicePool treats its preload as mandatory, `tts_node` retries only that engine before the first chunk, and production readiness requires the exact DashScope identity. A classified non-retryable billing failure therefore aborts initialization and produces HTTP 503 even when a local voice can speak.

The approved local backend is a Windows-host Qwen3-TTS 1.7B Base runtime using a Q5_K talker, Q8_0 predictor, FP16 ONNX codec components, and the `tosaka-rin-cn` voice reference. It produces 24 kHz mono audio with a measured warm first-audio latency near 0.22 seconds. Docker Desktop reaches it through `host.docker.internal`; Linux-host portability is out of scope.

## Goals / Non-Goals

**Goals:**

- Keep DashScope as the normal production backend while maintaining speech when either backend is available.
- Preserve streaming latency by forwarding local PCM as it is decoded.
- Prevent mixed voices within one utterance.
- Recover automatically without background paid synthesis.
- Keep `/ready` cached, sanitized, and operationally accurate.
- Preserve the existing persistent Qwen Docker service and unrelated dirty-worktree changes.

**Non-Goals:**

- Containerize the GGUF runtime for Linux CUDA.
- Support more than one primary and one fallback backend.
- Train or further tune the selected voice.
- Replace the existing Qwen service on port 8766.

## Decisions

### Use a registered composite provider

`FailoverTTS` implements the existing TTS interface and owns one DashScope child and one authenticated RemoteTTS child. Provider selection, retry, circuit state, child preload, and actual-backend metadata stay in the service layer; LangGraph continues to consume one engine.

Putting failover in `tts_node` was rejected because it would duplicate provider policy across streaming and non-streaming branches. A separate gateway was rejected because it would move DashScope credentials and monitoring into an additional process.

### Bind an utterance after its first chunk

The composite may retry or switch only before yielding the first non-empty chunk. Once a chunk is yielded, later primary failure terminates the stream and opens the circuit for subsequent utterances. This preserves event ordering and prevents audible voice splicing.

### Use one bounded circuit breaker

Non-retryable billing/authentication errors open immediately. Retryable connection, timeout, upstream, or protocol errors receive one pre-chunk retry before fallback. The circuit remains open for 300 seconds. The first request after expiry is the sole half-open primary probe; concurrent requests use the fallback. Only complete primary success closes the circuit.

### Extend the existing authenticated speech contract

The host service retains `/health`, authenticated `/ready` and `/v1/identity`, and `POST /v1/audio/speech`. `stream=true` returns chunked signed 16-bit little-endian PCM at 24 kHz mono; `stream=false` returns WAV. Identity headers and readiness payloads are validated against the configured provider, model, revision, voice, format, and sample rate.

The D-drive decoder proxy gains a supported per-task chunk subscription. The ASGI adapter consumes that subscription from a worker thread and does not poll private result dictionaries.

### Keep the host runtime independently persistent

Lifecycle commands manage a hidden Windows process with PID, log, and readiness files under the runtime directory. `anima-up` attempts to start and preflight it but continues if it is unavailable, because DashScope alone can satisfy readiness. `anima-down` preserves it; only explicit `host-tts-stop` releases it.

### Compute readiness from cached child state

Composite preload gathers both child results and succeeds if at least one is ready. The readiness snapshot reports the aggregate state, active backend, sanitized child states, circuit state, and retry delay. No readiness request performs provider I/O. Exact identity mismatch disables only the mismatched child.

## Risks / Trade-offs

- [D-drive runtime is a pinned local checkout] → Validate its commit and model file hashes at startup and fail only the local child on mismatch.
- [Docker Desktop may not reach the host listener] → Bind the authenticated service to the configured host interface and verify container-to-host `/ready` during lifecycle tests.
- [A cancelled native inference job may not stop immediately] → Cancel queued work immediately but reserve the single worker until native inference reaches a safe terminal state.
- [A primary failure after audio begins cannot be hidden] → Emit the existing failed stream terminal and route the next utterance locally.
- [Single-worker local inference can become busy] → Use a FIFO queue of two pending requests and return a sanitized busy response when full.
- [Metrics can leak text or create cardinality] → Permit only fixed backend, category, circuit-state, and outcome labels.

## Migration Plan

1. Add the host protocol and decoder chunk callback while retaining non-streaming compatibility.
2. Copy and hash-verify the approved reference under the D-drive runtime.
3. Add FailoverTTS, config validation, readiness, and telemetry behind a new provider type.
4. Change only the production TTS selection to the composite declaration.
5. Add lifecycle commands and Docker Desktop host URL/token wiring.
6. Run focused tests, impact-selected verification, fresh QA capture, and the persistent-Qwen Docker protocol.

Rollback selects `dashscope-seren` again in production and removes the host URL from the application environment. The host process may then be stopped explicitly; the existing Qwen container is unaffected.

## Open Questions

None. The Windows-only deployment boundary, 300-second cooldown, queue capacity, readiness semantics, latency thresholds, and selected model/voice identity are approved.

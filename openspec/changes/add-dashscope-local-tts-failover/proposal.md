## Why

Production readiness currently fails when DashScope realtime TTS rejects the account or is otherwise unavailable, even though a warm local Qwen3-TTS 1.7B runtime can provide intelligible low-latency Chinese speech. Animetta needs an operationally honest failover contract so speech and `/ready` remain available whenever either the cloud or local backend is healthy.

## What Changes

- Add a registered composite TTS provider that prefers DashScope and falls back to an authenticated Windows-host Qwen3-TTS service before the first audio chunk.
- Add bounded retry, a 300-second circuit breaker, single-flight half-open recovery, and no mixed voices within an utterance.
- Extend the remote TTS contract with authenticated 24 kHz mono PCM16 chunked streaming while retaining non-streaming WAV responses and exact identity validation.
- Add lifecycle commands that start and preserve the D-drive host runtime independently from Animetta and the existing persistent Qwen Docker service.
- Make TTS readiness operational: either backend is sufficient, a single-backend state is reported as degraded, and both unavailable is not ready.
- Report the actual backend used and low-cardinality failover, breaker, latency, and RTF telemetry without exposing text, credentials, exceptions, or host paths.

## Capabilities

### New Capabilities

- `tts-provider-failover`: Cloud-first streaming TTS selection, retry, circuit breaking, recovery, and per-utterance backend binding.
- `host-qwen-tts-runtime`: Authenticated Windows-host Qwen3-TTS GGUF service with exact identity and PCM16 streaming.

### Modified Capabilities

- `component-health-check`: TTS readiness becomes dual-backend, cached, and degradation-aware.
- `service-pool`: Shared service initialization accepts a composite TTS when at least one child backend preloads successfully.
- `prometheus-metrics-endpoint`: Export bounded TTS backend, failover, circuit, first-audio latency, and RTF metrics.

## Impact

- Affects TTS provider configuration/factory wiring, streaming synthesis, readiness snapshots, component probes, telemetry, and runtime lifecycle scripts.
- Adds one authenticated host endpoint at `host.docker.internal:8767`; the existing Qwen Docker service on port 8766 remains unchanged.
- Uses the pinned D-drive Qwen3-TTS 1.7B Q5 runtime and the approved Chinese voice reference; no Linux CUDA image is introduced.

## Context

The current review CLI owns a Vite lease, a fresh Playwright context per scene, an optional OBS Browser Source, append-only version-two evidence, and a static plugin registry. Its only plugin is the deterministic livestream visual catalog; OBS captures screenshots but does not monitor audio. The production TTS stack now has a registered `FailoverTTS` whose authenticated local route is a Qwen3-TTS 1.7B host on port 8767.

The existing review implementation is uncommitted work in the current workspace. This change must extend it in place without resetting, moving, or rewriting the frozen `text-boundaries` and `sparse` fixtures.

## Goals / Non-Goals

**Goals:**

- Exercise the production `FailoverTTS` with a deterministic billing failure and the real local fallback.
- Produce a fixed Chinese WAV, safe structured report, Chrome/OBS visual evidence, and an interactive human verdict.
- Enforce the approved first-audio, RTF, format, continuity, identity, and actual-backend gates.
- Keep plugin lifecycle, evidence extensions, and OBS audio changes optional and reversible.

**Non-Goals:**

- Adding a production fault-injection API or changing the production Docker topology.
- Adding this scene to the frozen livestream visual catalog.
- Recording OBS output or comparing cloud and local voices.
- Supporting a remote or Linux review harness in this change.

## Decisions

### 1. Use a separate review feature

Register `tts-failover` with one `billing-to-local` scene. This keeps normal livestream review deterministic and free from the D-drive runtime dependency. Appending the scene to `live` was rejected because every visual review would then require a real TTS host.

### 2. Use a loopback Python harness around production providers

The CLI starts one hidden `py -3.13` harness per review run. The harness constructs the production `DashScopeRealtimeTTS`, `RemoteTTS`, and `FailoverTTS` classes. A loopback DashScope-compatible WebSocket stub returns an `AccountNotInGoodStanding` error whose normalized code/message is classified as non-retryable billing. The fallback validates the exact 8767 identity before synthesis.

The harness accepts only the predefined scene and fixed text, protects its HTTP endpoints with a random per-run bearer token, and never exposes production routes. It collects streamed PCM into a WAV and atomically writes a sanitized JSON report.

### 3. Add optional plugin lifecycle hooks

`NodeReviewPlugin` gains capability flags plus optional `prepareRun`, `prepareAttempt`, and `disposeRun` hooks. A prepared attempt contributes URL parameters, technical assertions, optional artifacts, and structured observations. The CLI always disposes attempt/run resources with `finally`; the existing live plugin uses no hooks and retains its current behavior.

### 4. Keep version-two evidence backward compatible

Attempt artifacts gain optional `audio_wav` and `backend_report` records, and attempts gain optional scalar observations. Existing required fields and validators remain unchanged, so historical v1/v2 runs remain readable. Completeness for `tts-failover` additionally requires both new artifacts; stable rounds remain isolated by the feature fingerprint.

### 5. Route browser audio through the real livestream surface without recording

The feature routes to the existing `/live.html` review surface with the deterministic `empty` livestream scene plus a review-only `ttsFailover=1` query flag. A small module mounts a compact notification bar at the top-right, directly above the existing danmaku panel. The livestream background, Live2D stage, status rail, and danmaku surface remain visible and unchanged.

The notification loads the authenticated one-time WAV URL, shows only the safe takeover state and compact backend/performance details, plays the audio once, and exposes an `audio-ended` state used by Playwright assertions. It remains visible after playback in review mode so Chrome and OBS can capture a stable region. The standalone `tts-failover.html` entry is removed to avoid a second page shell and visual drift.

The harness also derives the same 50 Hz, 20 ms peak-amplitude envelope used by production non-streaming playback. That bounded envelope is returned only in the ephemeral synthesis response and is not persisted in the safe backend report. The review page waits for its standalone Live2D model to finish loading, stops any motion that could overwrite the mouth parameter, starts WAV playback and the envelope together, and records a low-cardinality `lip-sync-observed` assertion after a non-silent mouth target is applied.

For this feature the OBS adapter snapshots input settings and audio monitor type, enables `reroute_audio` and `OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT`, then restores the exact prior values on every exit path. While OBS owns monitored audio, the runner launches its separate Playwright Chromium with `--mute-audio`; browser-only reviews remain audible. This keeps Chrome available for assertions and evidence without playing the same WAV through two Windows output paths.

### 6. Gate on production performance definitions

First-audio time is measured from `FailoverTTS.synthesize_stream` invocation to its first non-empty PCM chunk. RTF is wall synthesis duration divided by PCM duration (`bytes / 2 / 24000`). Passing requires first audio at most 0.75 seconds and RTF at most 0.35 after one unrecorded warmup.

## Risks / Trade-offs

- **[OBS Browser Source autoplay differs across installations]** → Enable rerouted audio, wait for an explicit page playback state, and preserve a manual replay button for diagnostics.
- **[Chrome and OBS both play the review URL]** → Mute only the Playwright Chromium copy whenever monitored OBS audio is enabled, leaving OBS as the single listening source.
- **[Review WAV bypasses production lip sync]** → Carry a transient bounded 20 ms envelope, defer playback until the review model is ready, and assert that a non-silent mouth target was applied.
- **[Notification conflicts with livestream chrome]** → Match the existing 420 px danmaku width, anchor above the panel, and assert both the live shell and notification bounds in Playwright.
- **[Port or process collision]** → Bind both harness and protocol stub to OS-assigned loopback ports and pass their resolved URLs only in the run context.
- **[Host is cold or busy]** → Perform identity preflight and one warmup; retain failed WAV/report evidence and return a technical failure rather than weakening thresholds.
- **[Cleanup failure changes OBS state]** → Snapshot settings before mutation, make restore idempotent, and surface cleanup failure in attempt evidence.
- **[Secret disclosure]** → Pass the Qwen token only through the child environment, redact exception details, and keep the ephemeral review token out of persisted reports.

## Migration Plan

1. Add the optional interfaces and backward-compatible evidence readers first.
2. Add the harness and plugin behind the new feature ID.
3. Run contract tests with fake fallback and a real manual review with 8767.
4. Roll back by removing the plugin registration and optional fields; existing evidence remains readable.

## Open Questions

None.

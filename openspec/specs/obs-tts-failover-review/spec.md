# obs-tts-failover-review Specification
## Purpose
TBD - created by archiving change add-obs-tts-failover-review-scene. Update Purpose after archive.
## Requirements
### Requirement: OBS review exercises billing failover
The `tts-failover` review feature SHALL synthesize the fixed approved Chinese sentence through the production `FailoverTTS`, classify the primary failure as billing, and emit audio from the authenticated local fallback.

#### Scenario: Billing failure falls back locally
- **WHEN** the `billing-to-local` scene runs against the deterministic DashScope billing stub and a healthy 8767 host
- **THEN** the report SHALL identify `billing` as the primary error, `fallback` as the actual backend, and the composite as ready and degraded

#### Scenario: Fallback identity is incorrect
- **WHEN** the 8767 identity differs in provider, model, revision, quantization, runtime commit, voice, or sample rate
- **THEN** the attempt SHALL fail before OBS state is changed and SHALL not synthesize audio

### Requirement: Review audio meets the runtime contract
The review harness SHALL save complete 24 kHz mono PCM16 audio as a WAV and SHALL calculate first-audio latency and real-time factor from the streamed PCM.

#### Scenario: Audio satisfies all gates
- **WHEN** synthesis produces non-empty even-length PCM, first audio is at most 0.75 seconds, RTF is at most 0.35, and the stream completes
- **THEN** the technical audio assertions SHALL pass and the WAV and sanitized report SHALL be attached to the attempt

#### Scenario: Audio is invalid or incomplete
- **WHEN** synthesis is empty, contains an odd byte count, disconnects mid-stream, exceeds a threshold, is busy after bounded retry, or times out
- **THEN** the attempt SHALL fail while retaining all safe evidence produced before the failure

### Requirement: OBS provides interactive listening
The feature SHALL play the generated WAV through the existing livestream review surface with a compact top notification bar, an OBS Browser Source with audio monitoring enabled, and an interactive human verdict. It SHALL preserve the livestream background, Live2D stage, status rail, and danmaku surface, SHALL NOT add the scene to `LIVE_REVIEW_SCENES`, and SHALL NOT replace the broadcast surface with a standalone status page.

#### Scenario: Takeover notification appears over the livestream
- **WHEN** the `billing-to-local` review URL is opened
- **THEN** `/live.html` SHALL render its normal deterministic review surface and a top-right notification above the danmaku panel containing the local-takeover state and safe compact metrics
- **AND** the standalone `tts-failover.html` entry SHALL not be required

#### Scenario: Review audio drives the Live2D mouth
- **WHEN** the generated WAV is played on the livestream review surface
- **THEN** playback SHALL wait for the review Live2D model, apply a bounded transient 20 ms mouth envelope during the sentence, and record that a non-silent mouth target was observed
- **AND** the mouth envelope SHALL not be persisted in the safe backend report

#### Scenario: Operator approves the voice
- **WHEN** technical assertions pass and the operator hears a complete natural Chinese sentence without BGM, clipping, popping, or stalls
- **THEN** `pass` SHALL finalize the scene and preserve its Chrome, OBS, trace, WAV, report, and verdict evidence

#### Scenario: Operator requests another attempt
- **WHEN** the operator selects `adjust` or `redo`
- **THEN** only `billing-to-local` SHALL be synthesized again under a new immutable attempt number

### Requirement: Review harness remains local and safe
The harness SHALL listen only on loopback, accept only predefined review actions, use a random per-run bearer token, and exclude production credentials, source text overrides, raw exceptions, and absolute host paths from persisted output.

#### Scenario: Unauthorized request is received
- **WHEN** a request omits or mismatches the per-run bearer token
- **THEN** the harness SHALL reject it without returning audio, identity details, or diagnostic internals

#### Scenario: Review run terminates
- **WHEN** the run completes, fails, times out, or receives an interrupt
- **THEN** all harness and stub listeners SHALL stop and temporary resources SHALL be released idempotently

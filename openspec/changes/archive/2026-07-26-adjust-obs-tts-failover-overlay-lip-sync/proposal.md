## Why

The OBS TTS failover notification currently overlaps the danmaku panel, while the review mouth envelope appears consistently behind the audible sentence. The review needs a clear central safe-area placement and a deterministic lip-sync lead so operators can judge the fallback voice without visual interference.

## What Changes

- Move the compact failover notification from the top-right danmaku position to the horizontal center, below the top status and danmaku surfaces and above the Live2D face.
- Interpolate the review mouth envelope at a 60 ms lead and perceptually lift low speech frames while retaining bounded smoothing, silence reset, and post-motion Live2D parameter application.
- Sample the envelope inside the Live2D `beforeModelUpdate` callback so audio sampling and post-motion mouth application share one render frame instead of racing through separate animation-frame queues.
- Add deterministic layout and timeline-boundary tests, then replay the real OBS review for human comparison.
- Preserve the existing `live` review catalog, including the `text-boundaries` and `sparse` fixtures and assertions.

## Capabilities

### New Capabilities

- `obs-tts-failover-review-alignment`: Defines the non-overlapping notification safe area and the calibrated audio-to-mouth timing contract for the OBS failover review.

### Modified Capabilities

None.

## Impact

- `frontend/src/tts-failover/styles.css` and its focused notification tests.
- `frontend/src/live/review-lip-sync.ts`, the review Live2D playback path, and focused timing tests.
- OBS/Playwright review assertions and fresh evidence for the `tts-failover` feature.
- No production TTS provider, host-service protocol, audio artifact, or existing livestream review fixture changes.

## Context

The `tts-failover` OBS review mounts a compact notification inside the existing portrait livestream shell. It currently shares the top-right coordinates with the danmaku panel. The review mouth driver samples a 20 ms RMS envelope at `audio.currentTime` and then smooths the target, which makes the whole visible mouth sequence appear behind the audible sentence.

The change is review-surface-only. Production TTS selection, the 8767 host contract, generated WAV data, and the general Live2D audio path remain unchanged.

## Goals / Non-Goals

**Goals:**

- Keep the failover notification clear of the status rail, danmaku panel, and Live2D face in the 1080×1920 OBS review viewport.
- Correct the observed whole-sequence delay with an interpolated 60 ms mouth-envelope lead.
- Keep low speech frames visibly distinct during Live2D actions without turning silence into mouth movement.
- Eliminate the independent animation-frame race by sampling audio in the same Live2D model-update callback that commits the mouth value.
- Preserve bounded mouth values, current smoothing, post-motion parameter application, audio lifecycle cleanup, and existing review evidence.
- Make both adjustments directly testable before replaying the real OBS scene.

**Non-Goals:**

- Audio-device latency calibration or per-machine adaptive synchronization.
- Phoneme/viseme generation, model retraining, or changes to the WAV.
- Repositioning the normal danmaku panel or any existing `live` review fixture.
- Changing production Live2D lip sync outside the review-only failover path.

## Decisions

### Place the notification in the central upper safe area

The notification will be horizontally centered and placed below the top status/danmaku surfaces, around 230 px from the top of the 1080×1920 review viewport. Its existing compact width and visual tokens remain unchanged. The enter animation will preserve the horizontal centering transform while animating only the vertical offset.

This is preferred over shrinking it into the narrow top-row gap because a 420 px card cannot fit between the left status rail and right danmaku panel without overlap. Placing it at the screen center was rejected because it would cover the Live2D face.

### Interpolate the review mouth envelope at a 60 ms lead

The driver will sample at `audio.currentTime + 0.06` and linearly interpolate the adjacent 20 ms envelope frames. After the independent RAF race was removed, the operator found 59 ms only marginally slow, so the stable same-frame path settles on 60 ms.

The existing temporal smoothing remains in place. Before smoothing, a bounded power curve lifts low non-zero speech frames while preserving exact zero. Fresh evidence showed roughly 30% of active frames below 0.25; without the curve those frames are damped enough to become hard to see during larger body motions. Dynamic output-latency estimation was rejected because HTML audio/device clocks vary and the review needs deterministic evidence.

### Sample and apply within one Live2D frame

The review driver will expose an explicit sample operation. The Live2D post-motion binding invokes that operation at the beginning of `beforeModelUpdate`, then writes the resulting mouth value before the model commit. Review playback disables the driver's independent `requestAnimationFrame` loop. This removes the registration-order race where Pixi could render an old mouth value before a later callback sampled the current audio time.

### Keep calibration local and explicit

The lead and visibility exponent will be named review-only constants. Tests will use explicit fake `currentTime` values to prove interpolation, low-speech visibility, and start/end behavior. No new URL parameter or production setting is introduced.

### Validate with automated geometry and human replay

Focused tests will prove that the notification uses the central safe-area anchor and no longer asserts top-right alignment with the danmaku panel. Lip-sync tests will prove the interpolated 60 ms lead, visible low speech values, same-frame sampling without a second RAF, clamped mouth values, pause/end cleanup, and post-motion application. A fresh OBS/Playwright capture will then verify non-overlap and allow the operator to confirm perceived synchronization.

## Risks / Trade-offs

- **[Risk]** A fixed 60 ms lead may be slightly different on another audio device. → **Mitigation:** scope it to the deterministic review path and keep the lead as one named value that can be adjusted after replay.
- **[Risk]** Lifting weak speech frames may exaggerate background noise. → **Mitigation:** preserve exact zero, apply the curve only to the generated review envelope, and retain smoothing.
- **[Risk]** Manual sampling could stop if the Live2D ticker stops. → **Mitigation:** sampling is intentionally tied to model updates because no new mouth frame can be displayed while that ticker is stopped; stop/end paths still reset to zero.
- **[Risk]** Advancing the final frames may close the mouth shortly before the HTML audio element reports `ended`. → **Mitigation:** define and test the out-of-range envelope behavior explicitly and always reset to zero on stop/end.
- **[Risk]** Centering transforms can conflict with the existing entrance animation. → **Mitigation:** include horizontal centering in every animation keyframe or use an independent translate property supported by the OBS Chromium runtime.
- **[Risk]** Smaller preview dimensions may compress the safe area. → **Mitigation:** retain the existing responsive width cap and add a bounded responsive top offset without returning to the danmaku coordinates.

## Migration Plan

1. Add failing layout, 60 ms interpolation, and low-speech visibility tests.
2. Update the review-only CSS and mouth driver.
3. Run focused tests, frontend typecheck/build, OpenSpec strict validation, and affected quality tests.
4. Capture a fresh OBS review and ask for human synchronization confirmation.
5. Compare the calibrated result through focused replay; after same-frame sampling removes scheduling drift, settle on 60 ms and repeat acceptance.

## Open Questions

None. The operator selected the central safe area and confirmed that the mouth is uniformly behind the audio.

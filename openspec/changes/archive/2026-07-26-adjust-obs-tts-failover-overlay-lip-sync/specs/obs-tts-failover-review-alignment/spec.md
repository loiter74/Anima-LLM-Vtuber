## ADDED Requirements

### Requirement: Failover notification occupies the central upper safe area

The OBS TTS failover review SHALL render its compact notification horizontally centered below the top status and danmaku surfaces and above the Live2D face. It SHALL preserve the normal livestream surface and SHALL NOT overlap the danmaku panel in the 1080×1920 review viewport.

#### Scenario: Notification is shown during local takeover

- **WHEN** the `billing-to-local` scene displays the local takeover notification
- **THEN** the notification SHALL be horizontally centered in the upper safe area around 230 px from the viewport top
- **AND** its bounding box SHALL not intersect the danmaku panel or the Live2D face safe region

#### Scenario: Notification enters without losing horizontal centering

- **WHEN** the notification entrance animation runs
- **THEN** every animation state SHALL preserve the horizontal center anchor while changing only the intended vertical offset and opacity

### Requirement: Review mouth envelope leads audible playback by 60 milliseconds

The failover review mouth driver SHALL linearly interpolate its 20 ms envelope using a 60 ms lead relative to the HTML audio playback time. It SHALL perceptually lift low non-zero speech values while preserving exact silence, bounded smoothing, and post-motion Live2D parameter application, and SHALL reset the mouth to zero when playback pauses, ends, or is stopped.

#### Scenario: Active playback selects the advanced frame

- **WHEN** the audio element is playing at time `t`
- **THEN** the mouth driver SHALL interpolate adjacent envelope frames at `t + 0.06 seconds`
- **AND** the selected mouth value SHALL remain bounded between zero and one

#### Scenario: Low speech remains visible during model motion

- **WHEN** an active envelope frame contains a low non-zero speech value
- **THEN** the mouth driver SHALL lift its visible target before temporal smoothing
- **AND** an envelope value of zero SHALL remain exactly zero

#### Scenario: Audio sampling and mouth application share one model update

- **WHEN** Live2D emits `beforeModelUpdate` after motion, expression, and physics updates
- **THEN** the review driver SHALL sample the current audio time before writing the mouth parameter in that same callback
- **AND** review playback SHALL NOT schedule a competing mouth-sampling animation-frame loop

#### Scenario: Playback reaches a timeline boundary

- **WHEN** the advanced lookup is before the first valid frame or beyond the available envelope
- **THEN** the driver SHALL use deterministic bounded boundary behavior without throwing or reading an invalid value

#### Scenario: Playback is inactive

- **WHEN** playback is paused, ended, stopped, or the review is cleaned up
- **THEN** the mouth target SHALL return to zero and no stale animation frame SHALL continue updating the model

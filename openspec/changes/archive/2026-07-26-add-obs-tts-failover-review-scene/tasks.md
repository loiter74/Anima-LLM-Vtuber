## 1. Review harness

- [x] 1.1 Add failing Python tests for billing classification, exact fallback identity, fixed-text authorization, streaming WAV/report output, thresholds, invalid audio, busy, timeout, and idempotent cleanup.
- [x] 1.2 Implement the loopback DashScope billing stub and authenticated TTS failover review harness using production provider classes.
- [x] 1.3 Add the CLI/runtime lease that starts the harness with `py -3.13`, performs readiness preflight, and sanitizes child output.

## 2. Extensible review runtime

- [x] 2.1 Add failing TypeScript tests for plugin capabilities, run/attempt hooks, assertion merging, cleanup order, and backward-compatible audio/report evidence.
- [x] 2.2 Implement optional plugin lifecycle hooks, capability validation, typed audio/report artifacts, observations, and feature-specific completeness checks.
- [x] 2.3 Add failing OBS adapter tests and implement reversible Browser Source `reroute_audio` and monitor-and-output handling.

## 3. TTS failover feature

- [x] 3.1 Add failing catalog/plugin/page tests for the independent `tts-failover` feature and fixed `billing-to-local` scene.
- [x] 3.2 Implement the plugin, dedicated review page, stable assertions, one-time WAV playback, and interactive listening instructions.
- [x] 3.3 Register the feature and add a documented package command without changing the frozen live catalog.
- [x] 3.4 Add failing route, entry, overlay, bounds, and playback tests for rendering `billing-to-local` as a top notification over the existing livestream review surface.
- [x] 3.5 Route the feature through `/live.html`, mount the review-only notification module, and remove the standalone `tts-failover.html` entry without changing the frozen live catalog.
- [x] 3.6 Add a failing review-runner test and make monitored OBS the single audible output by muting only the parallel Playwright Chromium copy.
- [x] 3.7 Change the approved character-voice sentence to use `本小姐` and add a failing privacy assertion before removing synthesized text from the persisted backend report.
- [x] 3.8 Add failing envelope, deferred-playback, and mouth-driver tests before wiring the review WAV to the standalone Live2D model with a transient 20 ms timeline.

## 4. Verification

- [x] 4.1 Run Python 3.13 harness/provider tests and TypeScript review unit, type, lint, format, and build checks.
- [x] 4.2 Validate OpenSpec, canvas files, quality catalog, and `test-affected`.
- [x] 4.3 Run the real 8767 warm review and verify fallback identity, first audio <= 0.75 seconds, RTF <= 0.35, WAV format, and safe evidence.
- [x] 4.4 Capture fresh Playwright/OBS evidence with a human verdict and execute the Docker sub-agent protocol while proving the persistent 8766 Qwen container is unchanged.
- [x] 4.5 Re-run Python 3.13, OpenSpec strict, frontend checks, quality validation, `test-affected`, fresh OBS capture, and the Docker sub-agent protocol after the notification redesign.
- [x] 4.6 Re-run the focused frontend checks, OpenSpec strict validation, fresh single-output OBS listening capture, affected tests, and Docker protocol after the duplicate-audio fix.
- [x] 4.7 Re-run the real single-output review, affected tests, and Docker protocol after the approved sentence and report-privacy update.
- [x] 4.8 Capture fresh Chrome/OBS evidence whose automated assertions prove the review audio completed and a non-silent mouth target was applied.

## 1. Change Setup and Contracts

- [x] 1.1 Generate the required Obsidian Canvas diagrams for the event, capture, replay, and evaluation flow.
- [x] 1.2 Add failing tests for normalized event serialization, legacy conversion, and separate event metrics.
- [x] 1.3 Implement `LivestreamEvent`, `LivestreamEventType`, and `LivestreamEventMetrics` with public re-exports.

## 2. Gateway and Production Mapping

- [x] 2.1 Add failing fixture-driven tests for danmaku, gift, super-chat, entry/follow, like, popularity, connection, and unknown command normalization.
- [x] 2.2 Extend the Gateway/service event callback while retaining legacy message-callback behavior.
- [x] 2.3 Update `LivestreamSession` to count all events and submit only replyable events to the existing message/reply path.

## 3. Privacy-Safe Dataset Pipeline

- [x] 3.1 Add failing tests for in-memory actor aliases, text sanitization, payload whitelisting, manifest checksums, and validator rejection reasons.
- [x] 3.2 Implement streaming sanitization, JSONL dataset writing, manifests, workload statistics, and validation.
- [x] 3.3 Add optional locked live-capture dependencies and an anonymous collector with actionable dependency errors.

## 4. Deterministic Replay

- [x] 4.1 Add failing clock-injected tests for sequence order, base speed, high-heat burst timing, early stop, idempotent stop, and callback cleanup.
- [x] 4.2 Implement `ReplayDanmakuGateway`, speed/burst scheduling, replay metrics, and five-second lifecycle bounds.
- [x] 4.3 Add integration coverage from validated JSONL events through `LivestreamSession` and the legacy raw-message sink.

## 5. Evaluation CLI and Reports

- [x] 5.1 Add failing CLI tests for `capture`, `validate`, `replay`, and `report` command contracts.
- [x] 5.2 Implement transport/full-stack runner configuration, event/reply/resource evidence, gate calculations, and complete conversation logs.
- [x] 5.3 Implement deterministic 30-row sampling, manual scoring CSV, readiness calculation, and JSON/Markdown reports.

## 6. Verification and Baselines

- [x] 6.1 Run focused unit and integration tests, quality catalog validation, lint/type checks for changed modules, and `test-affected`.
- [x] 6.2 Run the persistent host-local Qwen startup protocol and collect fresh Playwright evidence for the replay surface.
- [x] 6.3 Document the nine-dataset collection runbook and record baseline execution as pending operator-provided room IDs rather than committing source-room data.
- [x] 6.4 Prove that the representative high-heat 1x timeline is long enough to complete every configured 30-, 60-, and 80-minute burst window and record fresh full-stack/Playwright evidence.

## 7. Evidence hardening

- [x] 7.1 Make event-sink failures part of accounting/runtime gates and report real/synthetic outcomes separately.
- [x] 7.2 Require full-stack RSS sampling to target the Animetta server container or an explicit server PID.
- [x] 7.3 Represent unreviewed safety/privacy/attribution as pending and accept only an explicit assessed JSON input.
- [x] 7.4 Bound every deployment HTTP retry/probe by the shared 300-second deadline and prohibit dependency installation or large-image builds in routine deployment.
- [x] 7.5 Re-run low, medium, and high 90-minute 1x full-stack baselines with server-targeted RSS and fresh QA evidence.
- [ ] 7.6 Complete the generated human scoring CSVs and explicit safety/privacy/attribution assessments.
- [x] 7.7 Support post-run safety assessments, require exactly 30 completed score rows, and generate a hash-only advisory content audit without mutating raw replay evidence.

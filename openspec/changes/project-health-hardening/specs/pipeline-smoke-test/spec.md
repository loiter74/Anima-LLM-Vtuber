## ADDED Requirements

### Requirement: HTTP route smoke probes
The smoke test suite SHALL include HTTP route probes for deployment-facing endpoints in addition to Socket.IO pipeline events.

#### Scenario: Singing recent route smoke test
- **WHEN** the smoke suite probes `/api/singing/recent` on a running server or lightweight ASGI app
- **THEN** the probe SHALL assert that the route returns HTTP 200 and valid JSON when no singing output files exist

#### Scenario: Singing subtitle route smoke test
- **WHEN** the smoke suite probes `/api/singing/subtitle/{filename}` with a missing subtitle file
- **THEN** the probe SHALL assert that the route returns HTTP 404 rather than raising an unhandled server exception

#### Scenario: Health route smoke test
- **WHEN** the smoke suite probes `/health`
- **THEN** the probe SHALL assert that the response is HTTP 200 and contains a top-level `status` field

### Requirement: Smoke tests avoid heavy model startup unless requested
HTTP route smoke probes SHALL be runnable without loading remote LLM, TTS, ASR, or large local model weights.

#### Scenario: Lightweight route probe
- **WHEN** route probes construct the ASGI app for route testing
- **THEN** they SHALL avoid service prewarming and external provider calls unless the test is explicitly marked integration

# live-danmaku-collector Specification

## Purpose
TBD - created by archiving change consolidate-live2d-review-and-danmaku-tools. Update Purpose after archive.
## Requirements
### Requirement: Live-room collection uses the production gateway
The live-room collector SHALL receive normalized danmaku messages and connection status through `DanmakuServiceGateway` and SHALL NOT instantiate the Bilibili transport library directly.

#### Scenario: A normalized message arrives
- **WHEN** the gateway invokes the message callback
- **THEN** the collector SHALL append the message to both configured output formats without reparsing provider payloads

#### Scenario: The operator interrupts collection
- **WHEN** the process receives a keyboard interrupt or termination request
- **THEN** the collector SHALL stop the gateway before closing its output writer

### Requirement: Live-room output is deterministic and local
The collector SHALL require a positive room ID, SHALL default to `scripts/danmaku_output`, and SHALL write one timestamped CSV file and one timestamped JSONL file containing normalized message fields.

#### Scenario: Output contains special characters
- **WHEN** a user name or message contains commas, quotes, or line breaks
- **THEN** the CSV writer SHALL escape it according to CSV rules and the JSONL writer SHALL produce one valid JSON object per physical line

#### Scenario: The writer is closed repeatedly
- **WHEN** cleanup invokes close more than once
- **THEN** the writer SHALL complete without raising or writing additional records

### Requirement: Credentials are not accepted as command arguments
The collector SHALL read an optional Bilibili session credential only from `BILIBILI_SESSDATA` and SHALL NOT include it in output, status messages, or exception text.

#### Scenario: No credential is configured
- **WHEN** `BILIBILI_SESSDATA` is absent
- **THEN** the collector SHALL start the gateway anonymously

#### Scenario: A credential is configured
- **WHEN** `BILIBILI_SESSDATA` is present
- **THEN** the collector SHALL pass it only to the gateway factory

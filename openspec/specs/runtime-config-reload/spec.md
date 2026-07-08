# runtime-config-reload Specification

## Purpose
Defines how runtime persona and lightweight LLM configuration reloads are validated, applied to active holders, and reported to callers.

## Requirements
### Requirement: Runtime reload is atomic and validated
The system SHALL reload persona YAML and lightweight LLM configuration as one validated runtime operation, preserving the previous active configuration when validation fails.

#### Scenario: Successful reload swaps active config
- **WHEN** the runtime config reload endpoint is called and the configured persona and LLM settings are valid
- **THEN** the system SHALL load the latest config and persona data from disk
- **THEN** the system SHALL increment the runtime config version
- **THEN** the reload response SHALL include `ok: true`, the active persona name, the new version, and refreshed areas

#### Scenario: Invalid persona preserves previous config
- **WHEN** the configured persona file is missing or fails validation during runtime reload
- **THEN** the system SHALL keep the previous active config and runtime config version
- **THEN** the reload response SHALL include `ok: false` and a redacted validation error
- **THEN** active sessions SHALL continue using the previous valid persona prompt

#### Scenario: Invalid LLM config preserves previous config
- **WHEN** lightweight LLM settings fail validation during runtime reload
- **THEN** the system SHALL keep the previous active config and runtime config version
- **THEN** active sessions SHALL continue using the previous valid LLM settings

### Requirement: Reload applies to active runtime holders
The system SHALL apply a successful runtime reload to every active holder of runtime configuration needed for subsequent conversations.

#### Scenario: Active session contexts receive reloaded config
- **WHEN** runtime reload succeeds while one or more sessions are active
- **THEN** each active session context SHALL reference the new `AppConfig`
- **THEN** each active session context SHALL expose the new runtime config version

#### Scenario: Route handlers receive reloaded config
- **WHEN** runtime reload succeeds
- **THEN** route handlers that serve persona/config events SHALL reference the new active config
- **THEN** future persona list or status requests SHALL report the reloaded persona data

#### Scenario: Active LLM prompt is refreshed when supported
- **WHEN** runtime reload succeeds and an active LLM engine supports `set_system_prompt`
- **THEN** the system SHALL apply the effective reloaded system prompt to that LLM engine

### Requirement: Reload result is structured and user-visible
The runtime reload API SHALL return structured status information that callers can use without parsing logs.

#### Scenario: Caller receives success metadata
- **WHEN** runtime reload succeeds
- **THEN** the API response SHALL include the active persona name, runtime config version, and refreshed domains

#### Scenario: Caller receives preserved-config error metadata
- **WHEN** runtime reload fails validation
- **THEN** the API response SHALL identify that the previous valid config remains active
- **THEN** the error message SHALL redact likely secret values

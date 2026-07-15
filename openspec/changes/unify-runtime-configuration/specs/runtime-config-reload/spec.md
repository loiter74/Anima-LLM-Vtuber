## MODIFIED Requirements

### Requirement: Runtime reload is atomic and validated
The system SHALL resolve persona and allowed lightweight LLM/UI changes as one candidate EffectiveConfig operation, preserving the previous immutable EffectiveConfig, hashes, version, and active engine identities when validation fails or when the diff contains a restart-required field.

#### Scenario: Successful reload swaps active config
- **WHEN** the runtime config reload endpoint is called and only the configured persona content or allowlisted lightweight LLM/UI settings changed and remain valid
- **THEN** the system SHALL resolve and validate the candidate configuration and persona data
- **THEN** the system SHALL increment the runtime config version
- **THEN** the reload response SHALL include `ok: true`, the active persona name, new version and hashes, and refreshed areas

#### Scenario: Invalid persona preserves previous config
- **WHEN** the configured persona file is missing or fails validation during runtime reload
- **THEN** the system SHALL keep the previous active EffectiveConfig, hashes, and runtime config version
- **THEN** the reload response SHALL include `ok: false` and a redacted validation error
- **THEN** active sessions SHALL continue using the previous valid persona prompt

#### Scenario: Invalid lightweight LLM config preserves previous config
- **WHEN** allowlisted lightweight LLM settings fail validation during runtime reload
- **THEN** the system SHALL keep the previous active EffectiveConfig, hashes, and runtime config version
- **THEN** active sessions SHALL continue using the previous valid LLM settings

#### Scenario: Provider lifecycle field changes
- **WHEN** the candidate changes profile, provider reference/type, model identity, voice, endpoint, authentication reference, service policy, or schema version
- **THEN** the system SHALL reject the reload without changing active configuration or engines
- **AND** the result SHALL include the exact redacted `restart_required` field paths

### Requirement: Reload applies to active runtime holders
The system SHALL publish one successful immutable EffectiveConfig snapshot to every active holder needed for subsequent conversations without allowing holders to reload or mutate their own copies.

#### Scenario: Active session contexts receive reloaded config
- **WHEN** runtime reload succeeds while one or more sessions are active
- **THEN** each active session context SHALL reference the new EffectiveConfig snapshot
- **THEN** each active session context SHALL expose the new runtime config version and hashes

#### Scenario: Route handlers receive reloaded config
- **WHEN** runtime reload succeeds
- **THEN** route handlers that serve persona/config events SHALL reference the new active EffectiveConfig
- **THEN** future persona list or status requests SHALL report the reloaded persona data and version

#### Scenario: Active LLM prompt is refreshed when supported
- **WHEN** runtime reload succeeds and an active LLM engine supports `set_system_prompt`
- **THEN** the system SHALL apply the effective reloaded system prompt to that LLM engine
- **AND** the engine's configured and resolved provider identities SHALL remain unchanged

### Requirement: Reload result is structured and user-visible
The runtime reload API SHALL return structured status information including configuration identity and restart requirements so callers do not parse logs or infer whether the previous configuration survived.

#### Scenario: Caller receives success metadata
- **WHEN** runtime reload succeeds
- **THEN** the API response SHALL include the active persona name, runtime config version, effective and semantic hashes, and refreshed domains

#### Scenario: Caller receives preserved-config error metadata
- **WHEN** runtime reload fails validation
- **THEN** the API response SHALL identify that the previous valid config remains active
- **THEN** the error message SHALL redact likely secret values and sensitive local paths

#### Scenario: Caller receives restart metadata
- **WHEN** runtime reload is rejected because lifecycle fields changed
- **THEN** the response SHALL include `ok: false`, `preserved: true`, the unchanged version/hashes, and redacted `restart_required` field paths

## Purpose
Defines the accepted behavior and requirements for the bilibili-config-model capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: BilibiliConfig Pydantic model
The system SHALL provide a `BilibiliConfig` Pydantic model at `config/providers/bilibili.py` that replaces the manual key-stripping of `bilibili` from `config.yaml` in `app.py`.

#### Scenario: Model loads from YAML
- **WHEN** `config/bilibili.yaml` contains `enabled: true, room_id: 12345, sessdata: "abc"`
- **THEN** `BilibiliConfig.model_validate(...)` returns a valid model with those values

#### Scenario: Model is optional in AppConfig
- **WHEN** `config/bilibili.yaml` does not exist
- **THEN** `AppConfig.bilibili` defaults to `None` and the app starts without error

### Requirement: bilibili block removed from manual stripping
The system SHALL remove `bilibili` from the `known_fields` set in `app.py. _load_services_mode()` and load it as a proper Pydantic field instead.

#### Scenario: bilibili loaded via its own config file
- **WHEN** `AppConfig.from_yaml()` is called
- **THEN** the `bilibili` config is loaded from `config/bilibili.yaml` (if exists) and assigned to `self.bilibili`

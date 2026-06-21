## ADDED Requirements

### Requirement: Touched UI surfaces avoid hardcoded colors
Frontend files touched by a health-hardening change SHALL use existing Animetta design-system tokens instead of new hardcoded hex, RGB, or RGBA color literals unless a token addition is explicitly approved and documented.

#### Scenario: Touched component contains new hardcoded color
- **WHEN** a modified Vue or CSS file introduces a new hardcoded color literal
- **THEN** the style gate SHALL fail or the change SHALL include a documented token addition in both the design-system token source and UnoCSS theme

#### Scenario: Existing hardcoded color remains outside touched scope
- **WHEN** an untouched legacy file contains hardcoded colors
- **THEN** the health-hardening change MAY leave it unchanged, but SHALL NOT add new hardcoded colors to that file

### Requirement: Style-guide OpenSpec state is synchronized
The style-guide OpenSpec tasks SHALL reflect the actual repository state for `STYLE_GUIDE.md` and related style governance artifacts.

#### Scenario: STYLE_GUIDE exists
- **WHEN** `STYLE_GUIDE.md` has been created with the required mapping, examples, and checklist
- **THEN** the corresponding OpenSpec tasks SHALL be marked complete or updated to describe remaining work accurately

#### Scenario: Style-guide task remains incomplete
- **WHEN** a style-guide task is not complete
- **THEN** the task text SHALL identify the missing artifact or verification step

# event-constants Specification

## Purpose
TBD - created by archiving change unify-socket-events. Update Purpose after archive.
## Requirements
### Requirement: Central event name registry

The system SHALL provide a central registry of all Socket.IO event names as TypeScript constants, used by both frontend emit/on calls and backend route registration.

#### Scenario: Frontend uses constants for emit
- **WHEN** frontend code sends a Socket.IO event
- **THEN** it SHALL reference a constant from the events registry (e.g., `Events.CHAT_SEND_TEXT`) instead of an inline string literal

#### Scenario: Backend syncs from registry
- **WHEN** backend registers Socket.IO event handlers
- **THEN** it SHALL load event names from a shared JSON file generated from the TypeScript constants

### Requirement: Consistent dot-notation naming

All event names in the registry SHALL use dot-notation format `{module}.{action}`.

#### Scenario: New event follows convention
- **WHEN** a developer adds a new Socket.IO event
- **THEN** the event name MUST match the pattern `{module}.{action}` where module is one of the defined namespaces (chat, history, config, persona, memory, sing, bilibili, minecraft, desktop, translation, system, meme)

#### Scenario: Existing events migrated
- **WHEN** the registry is created
- **THEN** all 48 existing events SHALL be mapped to their new dot-notation equivalents

### Requirement: Module namespace organization

Event constants SHALL be organized by module namespace for discoverability.

#### Scenario: Constants grouped by module
- **WHEN** a developer looks for chat-related events
- **THEN** they find all chat events under `Events.CHAT.*` (e.g., `Events.CHAT.SEND_TEXT`, `Events.CHAT.SEND_AUDIO`)

### Requirement: Type-safe event payloads

The registry SHALL include TypeScript type definitions for each event's payload.

#### Scenario: Emit with typed payload
- **WHEN** frontend emits `Events.CHAT_SEND_TEXT`
- **THEN** TypeScript SHALL enforce the payload matches `{ text: string; user_id?: string; from_name?: string }`

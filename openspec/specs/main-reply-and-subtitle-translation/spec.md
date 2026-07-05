# main-reply-and-subtitle-translation Specification

## Purpose
TBD - created by archiving change align-main-reply-style-and-subtitle-translation. Update Purpose after archive.
## Requirements
### Requirement: Main reply is the only authored answer
The system SHALL treat the main LLM reply stored in `response_text` as the only authored answer for a user turn.

#### Scenario: Chat turn produces one authored response
- **WHEN** a user message is processed
- **THEN** the system SHALL generate one main `response_text`
- **THEN** chat bubbles, original subtitles, memory storage, and TTS SHALL use that same `response_text`

#### Scenario: Subtitle translation does not answer the user
- **WHEN** subtitle translation is enabled for a completed response
- **THEN** the translation path SHALL translate `response_text`
- **THEN** the translation path SHALL NOT generate a second answer to the user message

### Requirement: Subtitle translation is stateless and history-safe
The system SHALL translate subtitles without mutating the main conversational history or reusing the main roleplay prompt.

#### Scenario: Message-based translator is available
- **WHEN** the LLM engine supports message-based chat calls
- **THEN** subtitle translation SHALL use isolated translation messages
- **THEN** subtitle translation SHALL NOT call the history-mutating chat method

#### Scenario: Translation fallback preserves history
- **WHEN** the LLM engine lacks a message-based chat call but exposes mutable history
- **THEN** subtitle translation SHALL restore the original history after translation
- **THEN** subsequent main replies SHALL NOT include translation prompts in history

#### Scenario: Translation cannot be made history-safe
- **WHEN** the LLM engine lacks a safe translation call path
- **THEN** the system SHALL skip subtitle translation for that turn
- **THEN** the system SHALL keep the main response visible and log a warning

### Requirement: Subtitle translation preserves meaning and Anima flavor
The system SHALL translate subtitles in a way that preserves the source reply's meaning and character tone without adding new information.

#### Scenario: Flavor-preserving translation
- **WHEN** `response_text` contains Anima-style phrasing such as fatigue, light sarcasm, or cyber tavern vocabulary
- **THEN** the translated subtitle SHALL preserve the tone where possible
- **THEN** the translated subtitle SHALL NOT introduce a new joke, apology, explanation, or answer absent from `response_text`

#### Scenario: Runtime markers are removed before translation
- **WHEN** `response_text` contains runtime markers such as emotion tags or affinity markers
- **THEN** the translation input SHALL remove those markers
- **THEN** the emitted subtitle translation SHALL NOT display those markers

### Requirement: Subtitle events are bound to a chat turn
The system SHALL attach a stable turn identity to original subtitle and translated subtitle events.

#### Scenario: Original subtitle event includes turn identity
- **WHEN** the output node emits the original `chat:sentence` payload for a response
- **THEN** the payload SHALL include `turn_id`

#### Scenario: Translation event includes matching turn identity
- **WHEN** the output node emits `chat:subtitle_translation`
- **THEN** the payload SHALL include the same `turn_id` as the source sentence event

#### Scenario: Missing upstream turn identity is handled
- **WHEN** the graph state does not already include a turn identity
- **THEN** the output node SHALL generate a stable turn identity for all subtitle events from that output pass

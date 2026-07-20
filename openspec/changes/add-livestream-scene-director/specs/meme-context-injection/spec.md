## ADDED Requirements

### Requirement: Scene-guided meme policy authority
The system SHALL treat the validated scene director meme policy as the sole active meme-strategy decision for a scene-guided livestream turn.

#### Scenario: Scene director selects a meme
- **WHEN** active `SceneGuidance` selects one approved meme with action `use`
- **THEN** the main prompt SHALL receive only that selected meme instruction
- **THEN** no post-response Humor LLM call SHALL select or author a different meme response

#### Scenario: Scene director suppresses memes
- **WHEN** guidance sets meme action to `none` or `avoid`
- **THEN** automatic meme injection and model-based humor rewriting SHALL not introduce a meme for that turn

#### Scenario: Turn has no scene guidance
- **WHEN** a normal chat turn or explicit meme invocation has no active scene guidance
- **THEN** existing meme retrieval, explicit invocation, and Humor configuration behavior SHALL remain unchanged

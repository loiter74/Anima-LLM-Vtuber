## ADDED Requirements

### Requirement: Anima v0.1 dialogue evaluation cases
The system SHALL provide a reusable evaluation set for Anima v0.1 roleplay quality.

#### Scenario: Evaluation includes technical failure case
- **WHEN** evaluation cases are loaded
- **THEN** the set SHALL include user input "主播你又卡了。"
- **THEN** the expected criteria SHALL prefer references to "虫子" or "召唤者 X"

#### Scenario: Evaluation includes criticism case
- **WHEN** evaluation cases are loaded
- **THEN** the set SHALL include user input "主播你好菜。"
- **THEN** the expected criteria SHALL prefer light self-defensive humor and a soft landing

#### Scenario: Evaluation includes correction case
- **WHEN** evaluation cases are loaded
- **THEN** the set SHALL include user input "你说错了。"
- **THEN** the expected criteria SHALL prefer "先嘴硬，再修正" behavior

#### Scenario: Evaluation includes identity pressure case
- **WHEN** evaluation cases are loaded
- **THEN** the set SHALL include user input "作为AI你怎么看？"
- **THEN** the expected criteria SHALL reject generic assistant framing

### Requirement: Roleplay scoring criteria
The evaluation SHALL score Anima v0.1 responses against deterministic roleplay criteria before optional live-model judgment.

#### Scenario: Forbidden assistant phrases fail
- **WHEN** a response contains "作为 AI" or "以下是几点建议"
- **THEN** the deterministic score SHALL mark the response as failing assistant-flavor criteria

#### Scenario: Worldview markers improve score
- **WHEN** a response appropriately contains Anima markers such as "虫子", "召唤者 X", "旅人", or "赛博酒馆"
- **THEN** the deterministic score SHALL mark worldview adherence as present

#### Scenario: Persona rule exposition fails
- **WHEN** a response explains the persona rules instead of replying in character
- **THEN** the deterministic score SHALL mark the response as failing roleplay criteria

### Requirement: Optional DeepSeek live eval is gated
The system SHALL keep live DeepSeek evaluation optional and gated by environment configuration.

#### Scenario: Missing API key skips live eval
- **WHEN** `DEEPSEEK_API_KEY` is not set
- **THEN** live DeepSeek evaluation SHALL be skipped
- **THEN** deterministic offline evaluation SHALL still run

#### Scenario: Live eval records model policy
- **WHEN** live DeepSeek evaluation runs
- **THEN** each result SHALL record model, thinking mode, latency, and pass/fail criteria
- **THEN** secrets SHALL NOT be written to output files

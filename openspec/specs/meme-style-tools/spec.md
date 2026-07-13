# meme-style-tools Specification

## Purpose
TBD - created by archiving change add-zhouli-meme-format. Update Purpose after archive.
## Requirements
### Requirement: Meme style tool registry
The system SHALL provide a reusable registry for named meme style tools.

#### Scenario: Built-in zhouli style is available
- **WHEN** meme style tools are loaded
- **THEN** the registry SHALL include a style with id `zhouli`
- **AND** the style SHALL include aliases containing `meme:zhouli`, `吾闻`, `古人云`, `先王制礼`, and `周礼体`
- **AND** the style SHALL include an explanation, ordered slots, render template, few-shot examples, trigger rules, avoid scenes, and cooldown defaults

#### Scenario: Unknown style lookup
- **WHEN** code requests a meme style id that is not registered
- **THEN** the registry SHALL return no style
- **AND** callers SHALL continue without raising an exception

### Requirement: Zhouli style rendering
The `zhouli` style SHALL render a modern event as mock-classical ritual reasoning that elevates a mundane action into rites, duty, friendship, title, or moral cultivation.

#### Scenario: Render zhouli text from complete slots
- **WHEN** all required `zhouli` slots are provided
- **THEN** the renderer SHALL produce text following this structure: opening authority, `并非...乃是...`, `今...看似...实则...`, `若...便不是...而是...`, and `此岂不合乎周礼？`
- **AND** the rendered text SHALL preserve the slot meanings without adding unrelated claims
- **AND** the rendered text SHALL stay under the configured maximum character count

#### Scenario: Missing required zhouli slots
- **WHEN** a caller attempts to render `zhouli` without required slots
- **THEN** the renderer SHALL fail deterministically with a validation error
- **AND** it SHALL identify the missing slot names

### Requirement: Explanation-first few-shot style prompt
The system SHALL build style extraction and generation prompt sections from meme style tools using explanation-first guidance followed by few-shot examples.

#### Scenario: Build zhouli prompt section
- **WHEN** the prompt builder receives the `zhouli` style
- **THEN** the resulting prompt section SHALL first explain the rhetorical mechanism of the style
- **AND** it SHALL list the required slots and their meanings
- **AND** it SHALL include at least the "疯狂星期四" and "不想上班" examples as few-shot demonstrations
- **AND** it SHALL instruct the model to use modern Chinese as the base and avoid obscure classical wording

#### Scenario: Add future meme style without collector rewrite
- **WHEN** a new meme style tool is registered
- **THEN** the prompt builder SHALL include it through the same style tool interface
- **AND** Bilibili collector prompt code SHALL NOT require style-specific branching for that new style

### Requirement: Explicit meme style invocation
The system SHALL support explicit text invocation of registered meme styles using `meme:<style_id>`.

#### Scenario: Invoke zhouli generation from natural-language intent
- **WHEN** the user enters `meme:zhouli 想让别人请疯狂星期四`
- **THEN** the system SHALL parse `zhouli` as the requested style id
- **AND** the remaining text SHALL be treated as the modern event or intent to transform
- **AND** the system SHALL return a rendered 周礼体 response following the registered `zhouli` style

#### Scenario: Invoke zhouli generation from complete slots
- **WHEN** a caller invokes `zhouli` with all required structured slots
- **THEN** the system SHALL render the style deterministically without requiring an LLM call

#### Scenario: Natural-language invocation uses few-shot slot filling
- **WHEN** a caller invokes `zhouli` with only a natural-language event or intent
- **THEN** the system SHALL use the style explanation, slot descriptions, and few-shot examples to fill required slots
- **AND** the final response SHALL be rendered from validated slots rather than returned as unstructured model prose

#### Scenario: Explicit invocation cannot fill required slots
- **WHEN** required `zhouli` slots cannot be filled from structured input or LLM output
- **THEN** the system SHALL return a clear validation error
- **AND** it SHALL NOT return a malformed partial 周礼体 template

### Requirement: Post-response meme decoration
The system SHALL support semi-active meme decoration as a post-response step instead of embedding meme style rules in Anima's main persona prompt.

#### Scenario: Semi-active zhouli quip after normal reply
- **WHEN** the user message is light banter, meme talk, or a mild complaint
- **AND** the cooldown policy allows use
- **THEN** Anima SHALL first generate the normal reply content
- **AND** the zhouli style tool MAY append or rewrite one short quip
- **AND** the final output SHALL preserve Anima's original intent and emotional stance

#### Scenario: Serious context blocks semi-active styling
- **WHEN** the scene is medical, mental-health, grief, legal, finance decision, serious work report, or another configured avoid scene
- **THEN** the meme router SHALL NOT trigger `zhouli` semi-actively
- **AND** the explicit `meme:zhouli` command SHALL remain the only way to request the style

#### Scenario: Cooldown limits repeated style use
- **WHEN** `zhouli` has been used within the configured cooldown turns
- **THEN** the meme router SHALL NOT trigger `zhouli` semi-actively
- **AND** explicit `meme:zhouli` invocation SHALL still be allowed

#### Scenario: Per-window cap limits repeated style use
- **WHEN** `zhouli` has reached the configured maximum uses within the recent turn window
- **THEN** the meme router SHALL NOT trigger `zhouli` semi-actively until the window allows it again

### Requirement: Structured style metadata
The system SHALL represent matched or generated meme styles with structured metadata rather than only plain text or tags.

#### Scenario: Matched or generated style metadata
- **WHEN** a meme candidate or generated response uses a registered style
- **THEN** the result SHALL carry `format_id`, `format_slots`, optional `format_confidence`, optional `rendered_text`, and optional `mode`
- **AND** `format_slots` SHALL use stable slot names from the style template

#### Scenario: Generic meme has no style metadata
- **WHEN** a meme candidate does not match a registered style
- **THEN** the candidate SHALL remain valid without `format_id`, `format_slots`, `format_confidence`, `rendered_text`, or `mode`

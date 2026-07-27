## ADDED Requirements

### Requirement: Isolated semantic Live2D performance review
The local review system SHALL provide an isolated `live2d-performance` feature that can exercise every version-one base expression and accent with deterministic Chinese audio without modifying the frozen livestream scene catalog.

#### Scenario: Semantic catalog is reviewed
- **WHEN** the operator runs the `live2d-performance` review feature
- **THEN** it SHALL display the active semantic label, start the expression with real audio, capture browser evidence, and return to calm after each sample

#### Scenario: Frozen fixtures remain unchanged
- **WHEN** the new feature is registered
- **THEN** the names, messages, timelines, and exact assertions of `text-boundaries` and `sparse` SHALL remain unchanged

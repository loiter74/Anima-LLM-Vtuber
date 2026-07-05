## MODIFIED Requirements

### Requirement: Prompt section ordering is deterministic
The prompt assembler SHALL render sections in a deterministic order that preserves instruction priority and keeps dynamic context separate from persistent persona content. Roleplay correction sections SHALL be ordered after static persona content and before memory context.

#### Scenario: Persona precedes runtime context
- **WHEN** persona and runtime personality sections are both present
- **THEN** the persona section SHALL appear before the runtime personality section

#### Scenario: Runtime context precedes memory context
- **WHEN** runtime personality and memory sections are both present
- **THEN** the runtime personality section SHALL appear before the memory section

#### Scenario: Roleplay correction precedes memory context
- **WHEN** roleplay correction and memory sections are both present
- **THEN** the roleplay correction section SHALL appear before the memory section
- **THEN** memory content SHALL NOT override the one-turn correction guidance

### Requirement: Prompt debug metadata
The prompt pipeline SHALL expose metadata that allows developers to inspect prompt composition without requiring full prompt text logs.

#### Scenario: Metadata lists included sections
- **WHEN** a compiled prompt is produced
- **THEN** its metadata SHALL include the names of included sections
- **THEN** its metadata SHALL include the number of included sections

#### Scenario: Metadata records warnings
- **WHEN** a prompt source fails or omits expected content
- **THEN** the compiled prompt SHALL include a warning entry describing the source and failure category
- **THEN** prompt compilation SHALL continue when a safe fallback exists

#### Scenario: Metadata identifies correction inclusion
- **WHEN** a roleplay correction section is included
- **THEN** prompt metadata SHALL identify that correction was included through section names
- **THEN** prompt metadata SHALL NOT log full prompt text by default

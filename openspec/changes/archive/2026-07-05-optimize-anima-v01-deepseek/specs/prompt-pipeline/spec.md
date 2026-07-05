## MODIFIED Requirements

### Requirement: Prompt section ordering is deterministic
The prompt assembler SHALL render sections in a deterministic order that preserves instruction priority and keeps dynamic context separate from persistent persona content. Runtime roleplay correction sections SHALL be ordered after static persona content and before memory context.

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

## ADDED Requirements

### Requirement: Realtime roleplay memory pressure control
The prompt pipeline SHALL cap memory pressure for realtime Anima roleplay so long memory and history context do not dilute the active persona.

#### Scenario: Realtime prompt caps memory section
- **WHEN** the interaction mode is realtime roleplay
- **THEN** the memory section SHALL use configured count or length caps
- **THEN** full worldbuilding documents SHALL NOT be inserted into the realtime compiled prompt

#### Scenario: Persona and correction remain close to active turn
- **WHEN** a realtime prompt contains persona, correction, and memory sections
- **THEN** persona and correction guidance SHALL appear before memory
- **THEN** the compiled prompt SHALL NOT duplicate old system prompts from conversation history

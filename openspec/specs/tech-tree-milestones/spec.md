# tech-tree-milestones Specification

## Purpose
TBD - created by archiving change mc-bot-tech-tree-unlock. Update Purpose after archive.
## Requirements
### Requirement: Wood Phase Milestone
The system SHALL check for wood phase completion.

#### Scenario: Wood phase complete
- **WHEN** inventory contains:
  - wooden_pickaxe >= 1
  - wooden_sword >= 1
  - crafting_table >= 1
- **THEN** wood phase milestone is achieved

### Requirement: Stone Phase Milestone
The system SHALL check for stone phase completion.

#### Scenario: Stone phase complete
- **WHEN** inventory contains:
  - stone_pickaxe >= 1
  - stone_sword >= 1
  - furnace >= 1
- **THEN** stone phase milestone is achieved

### Requirement: Iron Phase Milestone
The system SHALL check for iron phase completion.

#### Scenario: Iron phase complete
- **WHEN** inventory contains:
  - iron_pickaxe >= 1
  - iron_sword >= 1
  - iron_chestplate >= 1
- **THEN** iron phase milestone is achieved

### Requirement: Diamond Phase Milestone
The system SHALL check for diamond phase completion.

#### Scenario: Diamond phase complete
- **WHEN** inventory contains:
  - diamond_pickaxe >= 1
  - diamond_sword >= 1
- **THEN** diamond phase milestone is achieved

### Requirement: Milestone Check Function
The system SHALL provide a function to check milestone achievement.

#### Scenario: Check milestone
- **WHEN** check_milestone(phase, inventory) is called
- **THEN** returns True if all required items are present

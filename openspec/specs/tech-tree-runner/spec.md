# tech-tree-runner Specification

## Purpose
TBD - created by archiving change mc-bot-tech-tree-unlock. Update Purpose after archive.
## Requirements
### Requirement: TechTreeRunner Initialization
The system SHALL initialize TechTreeRunner with bridge, skill_library, and time budget.

#### Scenario: Create TechTreeRunner
- **WHEN** TechTreeRunner is created with bridge, skill_library, time_budget_minutes=60
- **THEN** runner initializes with 4 phases (wood, stone, iron, diamond)

### Requirement: Phase Execution
The system SHALL execute each phase sequentially with time budget.

#### Scenario: Execute wood phase
- **WHEN** runner starts and current_phase is "wood"
- **THEN** runner executes wood phase tasks for up to 10 minutes

#### Scenario: Phase timeout
- **WHEN** phase time budget is exceeded
- **THEN** runner marks phase as failed and advances to next phase

### Requirement: Milestone Checking
The system SHALL check phase milestones after each task execution.

#### Scenario: Wood milestone achieved
- **WHEN** inventory contains wooden_pickaxe + wooden_sword + crafting_table
- **THEN** runner advances to stone phase

#### Scenario: Milestone not achieved
- **WHEN** inventory does not contain required items
- **THEN** runner continues current phase

### Requirement: Skill Integration
The system SHALL search and use existing skills before LLM planning.

#### Scenario: Found matching skill
- **WHEN** task matches a skill in the library
- **THEN** runner executes the skill directly

#### Scenario: No matching skill
- **WHEN** no skill matches the task
- **THEN** runner uses LLM planner

### Requirement: Tech Tree Completion
The system SHALL detect when all phases are complete.

#### Scenario: All milestones achieved
- **WHEN** all 4 phases have achieved their milestones
- **THEN** runner marks tech tree as unlocked

#### Scenario: Time budget exceeded
- **WHEN** total time exceeds 60 minutes
- **THEN** runner stops and reports partial progress


# tech-tree-report Specification

## Purpose
TBD - created by archiving change mc-bot-tech-tree-unlock. Update Purpose after archive.
## Requirements
### Requirement: Report Generation
The system SHALL generate a tech tree unlock report after completion.

#### Scenario: Generate report
- **WHEN** tech tree run completes (success or timeout)
- **THEN** system generates a report with:
  - Total time
  - Phase completion status
  - Items collected
  - Skills learned
  - Skills reused

### Requirement: Report Format
The system SHALL generate reports in markdown format.

#### Scenario: Report structure
- **WHEN** report is generated
- **THEN** report contains:
  - Summary section
  - Phase details
  - Metrics table
  - Skill inventory

### Requirement: Report Persistence
The system SHALL save reports to file.

#### Scenario: Save report
- **WHEN** report is generated
- **THEN** report is saved to `data/tech_tree_reports/`

### Requirement: Benchmark Integration
The system SHALL integrate with BenchmarkRunner for metrics collection.

#### Scenario: Collect metrics
- **WHEN** tech tree run completes
- **THEN** BenchmarkMetrics is populated with:
  - time_to_milestone
  - unique_items_collected
  - distance_traveled
  - skills_created
  - skills_reused

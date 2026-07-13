# license-file Specification

## Purpose
TBD - created by archiving change consolidate-docs-rewrite-readme. Update Purpose after archive.
## Requirements
### Requirement: MIT LICENSE file present
The repository root SHALL contain a `LICENSE` file containing the MIT License text with the copyright line `Copyright (c) 2026 Cowork`.

#### Scenario: Visitor checks the project license
- **WHEN** a visitor opens the repository root
- **THEN** a `LICENSE` file exists at the top level
- **AND** its contents are the standard MIT License text
- **AND** the copyright holder is `Cowork` and the year is `2026`

#### Scenario: README license link resolves
- **WHEN** a reader clicks the `[MIT License](LICENSE)` link in `README.md`
- **THEN** the link resolves to the existing `LICENSE` file (not a 404)

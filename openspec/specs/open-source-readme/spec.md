# open-source-readme Specification

## Purpose
TBD - created by archiving change consolidate-docs-rewrite-readme. Update Purpose after archive.
## Requirements
### Requirement: Bilingual README structure
The repository SHALL provide `README.md` as the primary English entry point and `README.zh-CN.md` as a concise Chinese edition, with each file cross-linking to the other at the top via a language switcher.

#### Scenario: Visitor lands on the repo
- **WHEN** a visitor opens the repository on GitHub
- **THEN** `README.md` renders in English as the default project landing page
- **AND** the top of the file shows a language switcher linking to `README.zh-CN.md`

#### Scenario: Chinese-speaking user wants the Chinese edition
- **WHEN** the user clicks the Chinese link at the top of `README.md`
- **THEN** they are taken to `README.zh-CN.md`
- **AND** the top of that file links back to the English `README.md`

### Requirement: Portable quick-start commands
The README SHALL contain only portable commands: no hardcoded absolute paths, no machine-specific filesystem locations, and where a command differs between POSIX shells and PowerShell, both variants SHALL be shown.

#### Scenario: User on Linux/macOS follows quick start
- **WHEN** the user copies the quick-start commands into a POSIX shell
- **THEN** every command runs without editing (no `C:\` paths, no Windows-only syntax)

#### Scenario: User on Windows PowerShell follows quick start
- **WHEN** the user copies the PowerShell variant of an environment-variable command
- **THEN** it runs without modification

#### Scenario: Config setup
- **WHEN** the user reaches the configuration step
- **THEN** the README instructs `cp config/config.golden.yaml config/config.yaml` (a file that exists)
- **AND** does NOT reference the non-existent `config/config.default.yaml`

### Requirement: Accurate tech-stack representation
The README tech-stack section SHALL match the actual dependencies declared in `pyproject.toml` and `frontend/package.json`, including Python target version, backend framework, and the full frontend stack.

#### Scenario: Python version badge
- **WHEN** a reader checks the Python version badge
- **THEN** it shows `3.13` (matching `pyproject.toml` ruff/mypy targets), not `3.11+`

#### Scenario: Backend framework naming
- **WHEN** a reader checks the backend stack description
- **THEN** it says `Starlette + Socket.IO ASGI`, not `FastAPI`

#### Scenario: Frontend stack completeness
- **WHEN** a reader checks the frontend stack
- **THEN** it includes Vue 3, Vite, TypeScript, Pinia, UnoCSS, pixi.js, Live2D, and Electron (matching `frontend/package.json`)

### Requirement: Single consistent TTS provider description
The README SHALL describe the TTS providers in exactly one location using a single core/contrib provider table, rather than scattering conflicting provider lists across multiple sections.

#### Scenario: Reader looks up TTS providers
- **WHEN** a reader wants to know which TTS providers are available
- **THEN** they find one definitive provider table
- **AND** no other section of the README contradicts it with a different provider list

### Requirement: Concise README links to deep content
The README SHALL link to `docs/` for deep reference content (Socket.IO event tables, module deep-dives, API references) rather than duplicating that content inline.

#### Scenario: Reader needs Socket.IO event details
- **WHEN** a reader needs the full Socket.IO event catalog
- **THEN** the README links to `docs/reference/socket-api.md`
- **AND** the README itself does not contain the full event table

#### Scenario: Reader needs architecture detail
- **WHEN** a reader wants deeper architecture information
- **THEN** the README links to `docs/architecture/overview.md`

### Requirement: Chinese edition is concise
`README.zh-CN.md` SHALL cover quick start, architecture overview, and key documentation links, and SHALL defer to the English README and `docs/` for exhaustive detail.

#### Scenario: Chinese reader needs deep detail
- **WHEN** a Chinese reader needs full module documentation or API reference
- **THEN** `README.zh-CN.md` links them to the relevant English `docs/` page
- **AND** does not attempt to translate the entire documentation tree

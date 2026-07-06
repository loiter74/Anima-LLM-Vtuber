## Purpose

Define the isolated persona training lab boundary, data workflow, validation surface, and runtime export contract used to keep training experiments separate from the Anima runtime.

## Requirements

### Requirement: Independent Training Lab Boundary
The system SHALL provide an independent persona training lab project boundary separate from the Anima runtime repository.

#### Scenario: Training lab does not couple runtime imports
- **WHEN** Anima runtime code consumes persona training outputs
- **THEN** it SHALL consume generated JSON artifacts rather than importing training-lab Python modules

#### Scenario: Training dependencies remain outside runtime
- **WHEN** the training lab installs optional LoRA dependencies such as torch, transformers, peft, or accelerate
- **THEN** those dependencies SHALL NOT become required dependencies for starting Anima runtime

### Requirement: Minimal Redaction Corpus Pipeline
The training lab SHALL support a source-text pipeline that extracts reference dialogue and applies minimal redaction without rewriting the speaker's phrasing.

#### Scenario: Character dialogue is redacted without style rewriting
- **WHEN** a source row contains character dialogue with names, organizations, locations, or setting-specific terms
- **THEN** the lab SHALL replace those terms with placeholders while preserving the original sentence order, punctuation, and wording outside the redacted terms

#### Scenario: Raw private data stays local
- **WHEN** raw source text is extracted from Steam, VN, forum, or Bilibili sources
- **THEN** the lab SHALL store raw private text only under ignored local data paths or skip raw storage when configured

### Requirement: Dataset And Training Workflow
The training lab SHALL provide a file-based workflow for building redacted datasets, SFT splits, LoRA runs, evaluation results, and local reports.

#### Scenario: Dataset build produces auditable outputs
- **WHEN** a dataset build runs from redacted source rows
- **THEN** it SHALL produce train/eval JSONL files and a cleaning or build report with counts, source identifiers, and redaction metadata

#### Scenario: LoRA run writes a manifest
- **WHEN** a LoRA or smoke training run completes
- **THEN** it SHALL write a manifest with base model, dataset version, adapter path, training steps, loss summary, and evaluation summary

### Requirement: Interactive Local Validation
The training lab SHALL render an interactive local validation page from training manifests and evaluation outputs.

#### Scenario: Report supports inspection of held-out examples
- **WHEN** a user opens the generated validation page
- **THEN** the page SHALL show training metrics, evaluation accuracy, held-out examples, filtering controls, and prompt/reply preview controls derived from the manifest data

#### Scenario: Report is generated without a web service
- **WHEN** the validation page is generated
- **THEN** it SHALL be a self-contained local HTML artifact that can be opened without starting Anima backend or frontend services

### Requirement: Runtime Export Contract
The training lab SHALL export only reviewed runtime-consumable artifacts to Anima.

#### Scenario: Adapter manifest export
- **WHEN** a trained adapter is approved for runtime testing
- **THEN** the lab SHALL export an `adapter_manifest.json` containing base model, adapter path, dataset version, evaluation status, and safety boundary metadata

#### Scenario: Runtime style pack export
- **WHEN** style guidance is approved without requiring adapter loading
- **THEN** the lab SHALL export a `runtime_style_pack.json` containing prompt patch text, banned identity/source terms, style notes, and a limited number of reviewed example pairs

#### Scenario: Export excludes private raw text
- **WHEN** the lab writes runtime export artifacts
- **THEN** those artifacts SHALL NOT include raw private source text or unredacted copyrighted dialogue

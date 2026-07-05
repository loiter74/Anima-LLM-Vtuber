## Purpose
Defines the accepted behavior and requirements for the auto-benchmark capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: One-command auto benchmark
The benchmark tool SHALL support a single command that automates the full pipeline: start server, run tests, collect results, generate report.

#### Scenario: Auto mode execution
- **WHEN** user runs `python scripts/benchmark.py auto`
- **THEN** the tool SHALL start a mock server, send test prompts, collect timing data, and output a performance report

#### Scenario: Cleanup on exit
- **WHEN** the benchmark completes (success or failure)
- **THEN** the tool SHALL stop the mock server process and clean up temporary files

### Requirement: Mock configuration generation
The tool SHALL generate a temporary configuration that uses mock providers for all services.

#### Scenario: Mock config created
- **WHEN** auto benchmark starts
- **THEN** a temporary config file with `asr: mock`, `tts: mock`, `agent: mock`, `vad: mock` SHALL be created

### Requirement: Historical results tracking
Each benchmark run SHALL be saved for future comparison.

#### Scenario: Run saved
- **WHEN** auto benchmark completes
- **THEN** a JSON file SHALL be saved to `docs/benchmarks/runs/<timestamp>/` with all timing data

#### Scenario: Latest baseline updated
- **WHEN** auto benchmark completes
- **THEN** `docs/benchmarks/runs/latest.json` SHALL be updated

### Requirement: Baseline comparison
The report SHALL include a comparison with the previous run.

#### Scenario: Delta shown
- **WHEN** a previous run exists
- **THEN** the report SHALL show delta for each metric (P50, P95, P99, avg per node)

#### Scenario: Regression detection
- **WHEN** P95 latency increases by more than 20% from baseline
- **THEN** the report SHALL include a visible warning

### Requirement: OTel span collection
The benchmark SHALL collect and report OTel service-level spans from StatsStore.

#### Scenario: Service spans reported
- **WHEN** auto benchmark completes
- **THEN** the report SHALL include per-service timing (llm.api_call, tts.synthesize, etc.) from the spans table

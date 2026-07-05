## Purpose
Defines the accepted behavior and requirements for the benchmark-report capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Benchmark produces latency distribution report
The system SHALL run a configurable number of conversation turns against a mock LLM backend and record per-node latency, token counts, and error counts to StatsStore. Results SHALL be viewable on the existing Dashboard.

#### Scenario: Run benchmark with 100 turns
- **WHEN** user runs `python scripts/benchmark.py --turns 100 --mock`
- **THEN** 100 conversation turns are simulated end-to-end
- **AND** per-node latency (ASR, LLM, TTS, Emotion, Output) is recorded to StatsStore
- **AND** Dashboard displays P50, P95, P99 latency breakdown

#### Scenario: Benchmark output is exportable
- **WHEN** benchmark completes
- **THEN** a JSON summary is written to `docs/benchmarks/runs/<timestamp>.json`
- **AND** a Markdown report is written to `BENCHMARK.md`

### Requirement: Benchmark measures throughput under load
The system SHALL support concurrent turn execution with configurable concurrency to measure throughput.

#### Scenario: Concurrent load test
- **WHEN** user runs `python scripts/benchmark.py --turns 100 --concurrency 10`
- **THEN** up to 10 turns execute concurrently
- **AND** total QPS (turns/sec) is reported

### Requirement: Benchmark compares real vs mock performance
The system SHALL support benchmarking with real LLM providers for comparison against mock baseline.

#### Scenario: Real provider benchmark
- **WHEN** user runs `python scripts/benchmark.py --turns 20 --provider deepseek`
- **THEN** benchmark uses real DeepSeek API for LLM node
- **AND** results include token counts and cost estimates

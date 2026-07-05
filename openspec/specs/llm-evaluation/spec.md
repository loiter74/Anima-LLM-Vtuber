## Purpose
Defines the accepted behavior and requirements for the llm-evaluation capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Multi-LLM comparison script
The system SHALL provide a CLI script `scripts/eval_llm.py` that sends identical prompts to multiple configured LLM providers and compares responses using semantic similarity scoring.

#### Scenario: Compare two LLMs on factual accuracy
- **WHEN** user runs `python scripts/eval_llm.py --prompts eval_prompts.txt --providers deepseek,openai`
- **THEN** each prompt is sent to both DeepSeek and OpenAI
- **AND** responses are scored for semantic similarity against a reference answer
- **AND** latency per response is recorded
- **AND** results are output as JSON and Markdown table

### Requirement: Semantic similarity scoring
The system SHALL use `sentence-transformers` (model: `all-MiniLM-L6-v2`) to compute cosine similarity between each LLM response and the reference answer. Scores SHALL range from 0.0 (completely different) to 1.0 (identical meaning).

#### Scenario: Score calculation
- **WHEN** LLM response is "Paris is the capital of France"
- **AND** reference answer is "The capital of France is Paris"
- **THEN** similarity score is >= 0.85

#### Scenario: Divergent response scoring
- **WHEN** LLM response is "I don't know"
- **AND** reference answer is "Paris is the capital of France"
- **THEN** similarity score is <= 0.3

### Requirement: Quality-latency tradeoff table
The evaluation output SHALL include a table comparing each provider on: average similarity score, average latency, and a composite quality-per-second metric.

#### Scenario: Evaluation output format
- **WHEN** evaluation completes
- **THEN** output includes a table:

| Provider | Avg Similarity | Avg Latency (s) | Quality/sec |
|----------|---------------|-----------------|-------------|
| deepseek | 0.87          | 1.2             | 0.73        |
| openai   | 0.91          | 2.1             | 0.43        |

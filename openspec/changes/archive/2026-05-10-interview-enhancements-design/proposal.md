# Interview Enhancements — Detailed Design

**Date:** 2026-05-10
**Status:** Draft
**Change:** `interview-enhancements` (OpenSpec)

## Overview

Four targeted enhancements to produce quantitative evidence of engineering maturity.
Each is additive, zero breaking changes, and can be implemented independently.

---

## P1: Benchmark Report (Priority 1)

### Goal

Extend `scripts/benchmark.py` with configurable turns, concurrency, real-provider mode,
and structured JSON output. Results feed into StatsStore + existing Dashboard.

### Design

**New CLI interface** (replacing `sys.argv[1]`-based dispatch with `argparse`):

```bash
# Mock mode — 100 turns, 10 concurrent
python scripts/benchmark.py --turns 100 --concurrency 10 --mock

# Real provider mode — 20 turns via DeepSeek API
python scripts/benchmark.py --turns 20 --concurrency 5 --provider deepseek

# Report-only: regenerate from latest run
python scripts/benchmark.py report
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--turns` | int | 10 | Number of conversation turns |
| `--concurrency` | int | 1 | Concurrent turn execution (via `asyncio.Semaphore`) |
| `--provider` | str | None | Real LLM provider name (e.g. `deepseek`, `openai`) |
| `--mock` | flag | False | Force mock providers |
| `--output` | str | auto | JSON output path |

**Concurrency mechanism:**
```python
sem = asyncio.Semaphore(concurrency)
async def bounded_turn(text):
    async with sem:
        return await orch.process_text(text=text, ...)

results = await asyncio.gather(*[bounded_turn(t) for t in inputs])
```

**Real-provider mode:**
- Use `LLMFactory` to create a real LLM client in-process
- Use existing `MockTTS`/`MockASR` for other nodes (only LLM is real)
- Record `token_counts` from provider response metadata
- Estimate cost via provider-specific pricing (optional, configurable)

**Output (`docs/benchmarks/runs/<timestamp>.json`):**
```json
{
  "timestamp": "2026-05-10T12:00:00",
  "mode": "mock",
  "config": { "turns": 100, "concurrency": 10 },
  "qps": 8.3,
  "per_node": {
    "llm_node": { "avg_ms": 45, "p50": 40, "p95": 62 },
    "tts_node": { "avg_ms": 30, ... },
    "emotion_node": { "avg_ms": 5, ... },
    "output_node": { "avg_ms": 3, ... }
  },
  "token_counts": { "prompt": 0, "completion": 0 },
  "cost_estimate": 0.0
}
```

**Files affected:**
- `scripts/benchmark.py` — add `argparse`, concurrency, real-provider, JSON + Markdown report

---

## P2: Error Resilience (Priority 2)

### Goal

When LLM/TTS/ASR fail (timeout, rate-limit, network error), the node falls back to a
mock response, logs to StatsStore with error type, and continues. Next turn retries the
real provider.

### Design

**Catch-and-fallback pattern** (same pattern in all 3 nodes):

```
provider_call()
    ↓
asyncio.timeout(TIMEOUT_SECONDS) + try/except
    ↓
┌─────────┴─────────┐
│ Success           │ Failure
↓                   ↓
return result       log to StatsStore (error_type + provider)
                    return mock fallback text/audio
                    mark state with error metadata
```

**Node-specific fallbacks:**

| Node | Timeout | Fallback behavior |
|------|---------|-------------------|
| `llm_node` | 30s default | Return hardcoded apology text (no extra provider init) |
| `tts_node` | 30s default | Return empty `b""` audio bytes |
| `asr_node` | 15s default | Return empty string `""` |

**StatsStore integration:**
- `spans` table already has `status` (→ `"error"`) and `attributes` (TEXT) fields
- Store error metadata as JSON in `attributes` column:
  ```json
  {"error_type": "timeout", "provider": "deepseek", "timeout_s": 30}
  ```
- `traces` table already has `error_msg` field → append error summary
- No schema migration needed

**Error types to track:**
- `timeout` — provider call exceeded threshold
- `rate_limit` — HTTP 429 / rate limit error
- `network_error` — connection / DNS / TLS failure
- `invalid_response` — unexpected format or empty response

**Dashboard:**
- New "Error Rate" KPI card
- Read from existing `GET /api/stats/nodes` which already returns `error_count` and `error_rate`
- Formula: `(total_errors / total_calls) × 100%`

**Per-turn fallback guarantee:**
- Fallback state is NOT persisted across turns
- Each `process_text()` / `process_audio()` call starts fresh
- If real provider is healthy, next turn uses it normally

**Files affected:**
- `src/animetta/orchestration/graph/llm_node.py` — add `asyncio.timeout` around streaming loop
- `src/animetta/orchestration/graph/tts_node.py` — add `try/except` around `synthesize()`
- `src/animetta/orchestration/graph/asr_node.py` — add `try/except` around `transcribe()`
- `frontend/stats/stats.js` — add `fetchErrorRate()` function
- `frontend/stats/index.html` — add Error Rate KPI card

---

## P3: Redis Session Sharing (Priority 3)

### Goal

Optional Redis-backed LangGraph checkpoint. With `--redis-url`, session state persists
across restarts and is shared between backend instances. Without it, behavior is identical
to current in-memory `MemorySaver`.

### Design

**New file: `src/animetta/core/redis_checkpoint.py`**

```python
class AsyncRedisSaver(BaseCheckpointSaver):
    """Redis-backed checkpoint saver for LangGraph.

    Implements BaseCheckpointSaver protocol:
    - get(config) → Optional[dict]
    - put(config, checkpoint) → None
    - list(config, *, limit) → AsyncIterator[dict]
    """

    def __init__(self, redis_url: str):
        import redis.asyncio as aioredis
        self.redis = aioredis.from_url(redis_url)
        self.key_prefix = "checkpoint:"

    async def get(self, config) -> Optional[dict]:
        thread_id = config["configurable"]["thread_id"]
        data = await self.redis.get(f"{self.key_prefix}{thread_id}")
        return json.loads(data) if data else None

    async def put(self, config, checkpoint: dict) -> None:
        thread_id = config["configurable"]["thread_id"]
        await self.redis.set(
            f"{self.key_prefix}{thread_id}",
            json.dumps(checkpoint, default=str),
        )

    async def list(self, config, *, limit: int = 10):
        # Return recent checkpoints for the session
        ...
```

> **Note:** Verify exact `BaseCheckpointSaver` method signatures against the installed
> LangGraph version before implementation.

**Wire into server startup:**

```python
# src/animetta/core/socketio_server.py — new --redis-url CLI arg
# src/animetta/orchestration/graph/builder.py — accept any BaseCheckpointSaver

if redis_url:
    try:
        checkpointer = AsyncRedisSaver(redis_url)
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), falling back to MemorySaver")
        checkpointer = MemorySaver()
else:
    checkpointer = MemorySaver()

graph = build_graph(checkpointer=checkpointer, ...)
```

**Feature flag:**
- `--redis-url` flag only
- If absent → `MemorySaver` (current behavior, zero impact)
- If present but Redis unreachable → log warning, fall back to `MemorySaver`
- No config file change needed

**Dependency:**
- `redis[hiredis]` — optional, only imported when `--redis-url` is provided

**Files affected:**
- `src/animetta/core/redis_checkpoint.py` — new file
- `src/animetta/core/socketio_server.py` — add `--redis-url` arg, init `AsyncRedisSaver`
- `src/animetta/orchestration/graph/builder.py` — pass `checkpointer` through to `graph.compile()`

---

## P4: LLM Evaluation Framework (Priority 4)

### Goal

CLI script that sends identical prompts to multiple LLM providers, scores responses
via semantic similarity, and outputs comparison tables (JSON + Markdown).

### Design

**New file: `scripts/eval_llm.py`**

```bash
python scripts/eval_llm.py \
    --prompts eval_prompts.txt \
    --providers deepseek,openai \
    --output eval_results.json
```

**Algorithm:**
```
1. Load prompts from file (one per line, skip empty/comment lines)
2. For each provider, create LLM instance via LLMFactory
3. For each prompt → send to ALL providers in PARALLEL (asyncio.gather)
4. Record: response_text + latency_ms
5. Compute cosine similarity via sentence-transformers (all-MiniLM-L6-v2)
6. Aggregate per-provider: avg_similarity, avg_latency, quality_per_sec
7. Output: JSON file + print Markdown table
```

**Scoring:**
```python
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

model = SentenceTransformer('all-MiniLM-L6-v2')

def score_similarity(response: str, reference: str) -> float:
    emb1 = model.encode(response, normalize_embeddings=True)
    emb2 = model.encode(reference, normalize_embeddings=True)
    return float(cosine_similarity([emb1], [emb2])[0][0])
```

**Output example:**

```markdown
## LLM Evaluation — 2026-05-10

| Provider | Avg Similarity | Avg Latency (s) | Quality/sec |
|----------|---------------|-----------------|-------------|
| deepseek | 0.87          | 1.2             | 0.73        |
| openai   | 0.91          | 2.1             | 0.43        |
```

**Dependency:**
- `sentence-transformers` (with `torch`) — optional, only imported when running eval

**Files affected:**
- `scripts/eval_llm.py` — new file
- `eval_prompts.txt` — new file (10 sample prompts)

---

## Implementation Order

```
Week 1: P1 (Benchmark) — extend existing script, most visible output
Week 2: P2 (Error Resilience) — graph node changes, Dashboard update
Week 3: P3 (Redis Session Sharing) — new checkpoint backend
Week 4: P4 (LLM Evaluation) — standalone eval script
```

All 4 are independent — can be parallelized if needed.

## Dependencies

| Dependency | Version | Used By | Optional |
|-----------|---------|---------|----------|
| `redis[hiredis]` | >=5.0 | P3 Redis | ✅ Yes |
| `sentence-transformers` | >=3.0 | P4 LLM Eval | ✅ Yes |

## Testing Strategy

| Capability | Test approach |
|-----------|---------------|
| P1 Benchmark | Run `--turns 5 --mock`, verify JSON output shape + QPS > 0 |
| P2 Error Resilience | Mock timeout in LLM provider, verify fallback text, verify StatsStore error_type |
| P3 Redis | Start with `--redis-url`, verify session persists after restart |
| P4 LLM Eval | Run with 2 mock prompts, verify JSON + Markdown output |

## Risks

| Risk | Mitigation |
|------|-----------|
| LangGraph BaseCheckpointSaver API differs | Pin LangGraph version, test AsyncRedisSaver against installed API |
| sentence-transformers model download | Add `--model` flag for alternative lightweight models; document model size (~80MB) |
| hiredis build failure on Windows | Make entirely optional; fall back to pure-python redis |
| Benchmark concurrency may mask per-turn issues | Always record individual turn latencies, report P50/P95/P99 |

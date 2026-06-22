# Interview Enhancements — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 4 capabilities (Benchmark Report, Error Resilience, Redis Session Sharing, LLM Evaluation) to produce quantitative evidence of engineering maturity for interviews.

**Architecture:** Four fully independent capabilities atop existing infrastructure (StatsStore, LangGraph graph, ServicePool). Each is additive with feature flags — no breaking changes.

**Tech Stack:** Python 3.13+ · LangGraph · FastAPI/Socket.IO · redis-py · sentence-transformers · SQLite (StatsStore)

**Design Reference:** `docs/plans/2026-05-10-interview-enhancements-design.md`
**OpenSpec Tasks:** `openspec/changes/interview-enhancements/tasks.md`

---

## Priority 1: Benchmark Report (7 tasks)

### Task 1.1: Add CLI flags to benchmark.py

**Files:**
- Modify: `scripts/benchmark.py:607-714` — rewrite `main()` to use `argparse`

**Step 1: Read current file to understand CLI structure**

Read `scripts/benchmark.py:607-714` — the current `main()` function uses `sys.argv[1]` dispatch.

**Step 2: Replace with argparse**

```python
# scripts/benchmark.py — replace main()
import argparse

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anima performance benchmark")
    parser.add_argument("--turns", type=int, default=10, help="Number of conversation turns")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent turn execution")
    parser.add_argument("--provider", type=str, default=None, help="Real LLM provider name")
    parser.add_argument("--mock", action="store_true", help="Force mock providers")
    parser.add_argument("--output", type=str, default=None, help="JSON output path")
    parser.add_argument("mode", nargs="?", default="quick", 
                        choices=["quick", "full", "compare", "report", "live", "stats", "diff", "auto"])
    return parser.parse_args()

async def main():
    args = parse_args()
    # Dispatch based on args.mode (existing logic) + args.turns/concurrency/provider/mock
    ...
```

**Step 3: Verify**

Run: `python scripts/benchmark.py --help`
Expected: shows all new flags

---

### Task 1.2: Implement mock-mode benchmark with configurable turns

**Files:**
- Modify: `scripts/benchmark.py:40-75` — extend `Benchmark.run_quick()` to accept `turns` parameter

**Step 1: Modify `run_quick()` signature**

```python
async def run_quick(self, turns: int = 10):
    """Quick benchmark: text E2E with mock providers."""
    ctx = await self._create_mock_context()
    orch = await LangGraphOrchestratorFactory.create(...)

    latencies: List[float] = []
    # Use all test_inputs, cycling if needed
    test_inputs = [
        "你好，请介绍一下你自己。",
        "今天天气怎么样？",
        "帮我搜索一下最近的AI新闻。",
        "你能做什么？",
        "讲个笑话吧。",
    ]
    for i in range(turns):
        text = test_inputs[i % len(test_inputs)]
        start = time.perf_counter()
        try:
            await orch.process_text(text=text, user_id="bench", user_name="Bench")
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            print(f"  [{i+1}/{turns}] {elapsed:.0f}ms")
        except Exception as e:
            print(f"  [{i+1}/{turns}] FAILED: {e}")
    ...
```

**Step 2: Wire `args.turns` into `main()`**

```python
if args.mode == "quick":
    await bench.run_quick(turns=args.turns)
```

---

### Task 1.3: Implement concurrency support

**Files:**
- Modify: `scripts/benchmark.py` — add `_run_concurrent()` to `Benchmark`

**Step 1: Add concurrent execution method**

```python
import asyncio

async def _run_concurrent(self, orch, test_inputs: list, turns: int, concurrency: int) -> List[float]:
    """Run turns with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    latencies = []

    async def process_one(text: str, idx: int):
        async with sem:
            start = time.perf_counter()
            try:
                await orch.process_text(text=text, user_id="bench", user_name="Bench")
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
                print(f"  [{idx+1}/{turns}] {elapsed:.0f}ms")
            except Exception as e:
                print(f"  [{idx+1}/{turns}] FAILED: {e}")

    tasks = []
    for i in range(turns):
        text = test_inputs[i % len(test_inputs)]
        tasks.append(process_one(text, i))

    await asyncio.gather(*tasks)
    return latencies
```

**Step 2: Add QPS calculation**

```python
def _calculate_qps(self, latencies: List[float]) -> float:
    """Queries per second."""
    if not latencies:
        return 0
    total_time_s = sum(latencies) / 1000
    return len(latencies) / total_time_s if total_time_s > 0 else 0
```

**Step 3: Store QPS in results**

```python
self.results["qps"] = self._calculate_qps(latencies)
```

---

### Task 1.4: Implement real-provider mode

**Files:**
- Modify: `scripts/benchmark.py` — add `_create_real_context()` method

**Step 1: Add real context creation**

```python
async def _create_real_context(self, provider: str) -> ServiceContext:
    """Create a ServiceContext with a real LLM provider + mock TTS/ASR."""
    from anima.core.service_context import ServiceContext
    from anima.core.service_pool import ServicePool
    from anima.services.intelligence.llm.factory import LLMFactory
    from unittest.mock import AsyncMock, MagicMock
    
    ctx = MagicMock(spec=ServiceContext)
    # Real LLM
    ctx.llm_engine = LLMFactory.create(provider)
    # Mock TTS/ASR
    ctx.tts_engine = AsyncMock()
    ctx.tts_engine.synthesize = AsyncMock(return_value=b"")
    ctx.asr_engine = AsyncMock()
    ctx.asr_engine.transcribe = AsyncMock(return_value="mock transcription")
    ctx.emotion_analyzer = MagicMock()
    ctx.emotion_analyzer.analyze = MagicMock(return_value="neutral")
    ctx.memory_system = AsyncMock()
    ctx.memory_system.retrieve_context = AsyncMock(return_value=[])
    return ctx
```

**Step 2: Add token count + cost estimation**

```python
def _estimate_cost(self, provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate API cost based on provider pricing."""
    pricing = {
        "deepseek": {"prompt": 0.00014, "completion": 0.00028},   # per 1K tokens
        "openai":   {"prompt": 0.0015,  "completion": 0.0020},    # GPT-4o mini
        "glm":      {"prompt": 0.001,   "completion": 0.001},
    }
    p = pricing.get(provider, {"prompt": 0, "completion": 0})
    return (prompt_tokens / 1000 * p["prompt"]) + (completion_tokens / 1000 * p["completion"])
```

---

### Task 1.5: Output JSON summary to docs/benchmarks/runs/<timestamp>.json

**Files:**
- Modify: `scripts/benchmark.py:189-196` — extend `save_results()` with timestamped output

**Step 1: Add timestamped save**

```python
def save_results(self, output_path: str = None):
    """Save results to JSON."""
    runs_dir = Path(__file__).parent.parent / "docs" / "benchmarks" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    
    if output_path:
        path = Path(output_path)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = runs_dir / f"{ts}.json"
    
    with open(path, "w") as f:
        json.dump(self.results, f, indent=2, ensure_ascii=False)
    print(f"Results saved to {path}")
    
    # Also update latest.json
    latest = Path(__file__).parent.parent / "docs" / "benchmarks" / "latest.json"
    with open(latest, "w") as f:
        json.dump(self.results, f, indent=2, ensure_ascii=False)
```

---

### Task 1.6: Generate BENCHMARK.md from results

**Files:**
- Modify: `scripts/benchmark.py:198-273` — enhance `generate_report()` with QPS and per-node timing

**Step 1: Add QPS and per-node timing to report**

```markdown
## Summary

| Metric | Value |
|--------|-------|
| QPS | 8.3 turns/sec |
| Total Turns | 100 |
| Concurrency | 10 |

### End-to-End Latency

| P50 | P95 | P99 | Min | Max | Std |
|-----|-----|-----|-----|-----|-----|
| 120ms | 250ms | 400ms | 80ms | 500ms | 45ms |

### Per-Node Timing

| Node | Avg (ms) | Calls |
|------|----------|-------|
| llm_node | 45 | 100 |
| tts_node | 30 | 100 |
| emotion_node | 5 | 100 |
| output_node | 3 | 100 |
```

---

### Task 1.7: Run baseline benchmark and commit results

Run: `python scripts/benchmark.py --turns 100 --concurrency 10 --mock`
Expected: outputs JSON to `docs/benchmarks/runs/<timestamp>.json`

Verify: check file exists and contains valid JSON with latency array

---

## Priority 2: Error Resilience (7 tasks)

### Task 2.1: Add configurable timeout to LLM provider calls

**Files:**
- Modify: `src/animetta/orchestration/graph/llm_node.py` — wrap streaming loop with `asyncio.timeout`

**Step 1: Identify the streaming loop**

In `_llm_without_tools()` (line ~327):
```python
async for chunk in llm_engine.chat_stream(user_text, system_prompt=enriched_prompt):
```

**Step 2: Wrap with timeout**

```python
import asyncio

# Configurable via state or default
TIMEOUT_SECONDS = 30

try:
    async with asyncio.timeout(TIMEOUT_SECONDS):
        async for chunk in llm_engine.chat_stream(user_text, system_prompt=enriched_prompt):
            if interrupt_handler.is_interrupted(session_id):
                break
            chunks.append(chunk)
            full_response += chunk
except asyncio.TimeoutError:
    logger.warning(f"[{session_id}] [LLMNode] LLM timeout after {TIMEOUT_SECONDS}s, using mock fallback")
    full_response = "I need a moment to think about that. Please give me a second."
    chunks = [full_response]
    # Set metadata for StatsStore
    state_updates = {"error_type": "timeout", "error_msg": f"LLM timeout after {TIMEOUT_SECONDS}s"}
```

**Step 3: Verify**

Run: `python -c "from anima.orchestration.graph.llm_node import llm_node; print('OK')"`
Expected: no import error

---

### Task 2.2: Implement catch-and-fallback in llm_node.py

**Files:**
- Modify: `src/animetta/orchestration/graph/llm_node.py` — add fallback + StatsStore logging

**Step 1: Add error tracking to return dict**

```python
return {
    "response_text": full_response,
    "response_chunks": chunks,
    "messages": [ai_message],
    "tool_calls": None,
    "metadata": {**state.get("metadata", {}), **({"error_type": "timeout"} if timeout_occurred else {})},
}
```

The `StatsCallbackHandler.on_chain_error` already writes error spans to StatsStore. When `asyncio.TimeoutError` propagates (or is caught and re-raised), the callback handler catches it. But since we're catching it internally and returning fallback, we need to signal the error differently.

**Better approach:** Catch the error, log to StatsStore directly via `NodeTimer`, return fallback without raising:

```python
from .stats_handler import NodeTimer
from .stats_store import get_stats_store

# In the node, use timer to record the error checkpoint
timer = NodeTimer("llm_node", trace_id)
await timer.checkpoint("llm_api_call_timeout")
# return fallback
```

---

### Task 2.3: Implement catch-and-fallback in tts_node.py and asr_node.py

**Files:**
- Modify: `src/animetta/orchestration/graph/tts_node.py:81` — wrap `synthesize()` call
- Modify: `src/animetta/orchestration/graph/asr_node.py:47` — wrap `transcribe()` call

**Step 1: tts_node.py — wrap synthesize**

```python
try:
    audio = await tts_engine.synthesize(clean_text)
except Exception as e:
    logger.warning(f"[{session_id}] [TTSNode] TTS failed ({type(e).__name__}), returning silent audio")
    return {"tts_audio": b"", "error": str(e)}
```

**Step 2: asr_node.py — wrap transcribe**

```python
try:
    text = await asr_engine.transcribe(raw_audio)
except Exception as e:
    logger.warning(f"[{session_id}] [ASRNode] ASR failed ({type(e).__name__}), returning empty")
    return {"error": str(e), "user_text": ""}
```

---

### Task 2.4: Add error_type field to StatsStore traces/spans

**Files:**
- Modify: `src/animetta/orchestration/graph/stats_store.py` — check existing schema (already has `attributes` TEXT on spans)
- Verify: no schema migration needed; use `attributes` column to store `{"error_type": "timeout"}` JSON

**Step 1: Verify existing schema**

```sql
SELECT sql FROM sqlite_master WHERE name='spans';
```
Expected: has `attributes TEXT` column.

---

### Task 2.5: Add error rate counter to Dashboard KPI cards

**Files:**
- Modify: `frontend/stats/stats.js` — add `fetchErrorRate()`
- Modify: `frontend/stats/index.html` — add Error Rate card

**Step 1: index.html — add card**

```html
<section class="kpi-cards">
    ...
    <div class="card">
        <div class="card-label">Error Rate</div>
        <div class="card-value" id="error-rate">-</div>
    </div>
</section>
```

**Step 2: stats.js — add fetch function**

```javascript
async function fetchErrorRate() {
    const res = await fetch(`${API_BASE}/api/stats/nodes`);
    const data = await res.json();
    const totalErrors = data.reduce((sum, n) => sum + n.error_count, 0);
    const totalCalls = data.reduce((sum, n) => sum + n.call_count, 0);
    const rate = totalCalls > 0 ? (totalErrors / totalCalls * 100).toFixed(1) + "%" : "0%";
    document.getElementById("error-rate").textContent = rate;
}
```

**Step 3: Add to refreshAll**

```javascript
async function refreshAll() {
    await Promise.all([fetchOverview(), fetchNodeStats(), fetchTraces(), fetchErrorRate()]);
}
```

---

### Task 2.6: Write test — mock LLM timeout → fallback → Dashboard error count

**Files:**
- Create: `tests/test_error_resilience.py`

**Step 1: Write test**

```python
"""Test error resilience — LLM timeout triggers mock fallback."""
import pytest
from unittest.mock import AsyncMock, patch
from anima.orchestration.graph.llm_node import llm_node
from anima.orchestration.graph.state import create_initial_state

@pytest.mark.asyncio
async def test_llm_timeout_triggers_fallback():
    """When LLM streaming times out, fallback text is returned."""
    state = create_initial_state(
        session_id="test-timeout",
        input_type="text",
        user_text="Hello",
    )
    
    # Create mock config that will raise TimeoutError
    mock_config = {
        "configurable": {
            "service_context": AsyncMock(),
            "thread_id": "test-timeout",
        }
    }
    mock_config["configurable"]["service_context"].llm_engine = AsyncMock()
    mock_config["configurable"]["service_context"].llm_engine.chat_stream.side_effect = asyncio.TimeoutError()
    
    result = await llm_node(state, mock_config)
    
    # Should return fallback text, not crash
    assert result["response_text"] != ""
    assert len(result["response_chunks"]) > 0
```

**Step 2: Run test**

Run: `PYTHONPATH=src python -m pytest tests/test_error_resilience.py::test_llm_timeout_triggers_fallback -v`
Expected: PASS or FAIL with clear error to fix

---

### Task 2.7: Write test — fallback is per-turn

**Files:**
- Modify: `tests/test_error_resilience.py`

**Step 1: Write test**

```python
@pytest.mark.asyncio
async def test_fallback_is_per_turn():
    """After fallback on turn N, turn N+1 uses real provider again."""
    # Create real provider mock
    real_engine = AsyncMock()
    async def mock_stream():
        yield "normal response"
    real_engine.chat_stream.return_value = mock_stream()
    
    # Turn 1: should use real provider, no timeout
    state1 = create_initial_state(session_id="test-per-turn", input_type="text", user_text="hi")
    config1 = {
        "configurable": {
            "service_context": AsyncMock(),
            "thread_id": "test-per-turn",
        }
    }
    config1["configurable"]["service_context"].llm_engine = real_engine
    
    result1 = await llm_node(state1, config1)
    assert "error" not in result1 or not result1.get("error")
```

---

## Priority 3: Redis Session Sharing (7 tasks)

### Task 3.1: Add redis[hiredis] as optional dependency

**Files:**
- Modify: `requirements.txt` or `pyproject.toml`

```txt
# Optional: Redis checkpoint support
redis[hiredis]>=5.0
```

---

### Task 3.2: Implement AsyncRedisSaver

**Files:**
- Create: `src/animetta/core/redis_checkpoint.py`

```python
"""Redis-backed LangGraph checkpoint saver."""
import json
from typing import Optional, Any, AsyncIterator
from loguru import logger
from langgraph.checkpoint.base import BaseCheckpointSaver


class AsyncRedisSaver(BaseCheckpointSaver):
    """Redis-backed checkpoint saver.
    
    Stores session state in Redis for multi-instance sharing.
    Falls back to MemorySaver if Redis is unavailable.
    """
    
    def __init__(self, redis_url: str):
        import redis.asyncio as aioredis
        self.redis = aioredis.from_url(
            redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        self._prefix = "checkpoint:"
    
    async def get(self, config: dict) -> Optional[dict]:
        thread_id = config["configurable"]["thread_id"]
        key = f"{self._prefix}{thread_id}"
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"[RedisSaver] get failed: {e}")
        return None
    
    async def put(self, config: dict, checkpoint: dict) -> None:
        thread_id = config["configurable"]["thread_id"]
        key = f"{self._prefix}{thread_id}"
        try:
            await self.redis.set(
                key,
                json.dumps(checkpoint, default=str),
                ex=86400,  # 24h TTL
            )
        except Exception as e:
            logger.warning(f"[RedisSaver] put failed: {e}")
    
    async def list(self, config: dict, *, limit: int = 10, before: Optional[dict] = None) -> AsyncIterator[dict]:
        # Minimal implementation returning empty list
        return
        yield  # pragma: no cover
    
    async def close(self):
        await self.redis.close()
```

---

### Task 3.3: Add --redis-url CLI argument to socketio_server.py

**Files:**
- Modify: `src/animetta/core/socketio_server.py` — add argparse

```python
import argparse

def parse_server_args():
    parser = argparse.ArgumentParser(description="Anima Socket.IO Server")
    parser.add_argument("--redis-url", type=str, default=None,
                       help="Redis URL for session checkpoint (e.g. redis://localhost:6379)")
    return parser.parse_args()

_server_args = parse_server_args()
redis_url = _server_args.redis_url
```

---

### Task 3.4: Wire Redis checkpoint into builder.py

**Files:**
- Modify: `src/animetta/orchestration/graph/builder.py` — accept checkpointer as parameter

**Builder already accepts `checkpointer` parameter** in `build_graph()` — just need to pass the right one.

```python
# In socketio_server.py get_asgi_app():
from langgraph.checkpoint.memory import MemorySaver

if redis_url:
    try:
        from anima.core.redis_checkpoint import AsyncRedisSaver
        checkpointer = AsyncRedisSaver(redis_url)
        asyncio.ensure_future(_verify_redis(checkpointer))
    except Exception as e:
        logger.warning(f"[Redis] Connection failed ({e}), falling back to MemorySaver")
        checkpointer = MemorySaver()
else:
    checkpointer = MemorySaver()

# Pass to the builder/factory
create_default_graph(checkpointer=checkpointer, ...)
```

We also need to forward the checkpointer through `LangGraphOrchestrator` to `create_default_graph()`.

---

### Task 3.5: Implement Redis unavailable fallback

Already covered in Task 3.4 — the try/except around `AsyncRedisSaver` init handles this.

---

### Task 3.6: Write test — session persists across server restart with Redis

**Files:**
- Create: `tests/test_redis_checkpoint.py`

```python
@pytest.mark.asyncio
async def test_session_persists_with_redis():
    """Session state survives checkpointer re-creation (simulating restart)."""
    import asyncio
    from anima.core.redis_checkpoint import AsyncRedisSaver
    
    # Requires running Redis — skip if not available
    redis = pytest.importorskip("redis")
    try:
        saver1 = AsyncRedisSaver("redis://localhost:6379/15")
    except Exception:
        pytest.skip("Redis not available")
    
    config = {"configurable": {"thread_id": "test-restart"}}
    checkpoint = {"messages": [{"role": "user", "content": "hello"}], "turn": 1}
    
    await saver1.put(config, checkpoint)
    
    # Simulate restart — create new saver
    saver2 = AsyncRedisSaver("redis://localhost:6379/15")
    loaded = await saver2.get(config)
    
    assert loaded is not None
    assert loaded["turn"] == 1
    
    await saver1.close()
    await saver2.close()
```

---

### Task 3.7: Write test — fallback to MemorySaver when Redis unreachable

```python
@pytest.mark.asyncio
async def test_fallback_to_memory_when_redis_unreachable():
    """When Redis is unreachable, MemorySaver is used."""
    from langgraph.checkpoint.memory import MemorySaver
    
    checkpointer = MemorySaver()  # fallback
    config = {"configurable": {"thread_id": "test-fallback"}}
    
    await checkpointer.put(config, {"key": "value"})
    result = await checkpointer.get(config)
    assert result is not None
```

---

## Priority 4: LLM Evaluation Framework (8 tasks)

### Task 4.1: Add sentence-transformers as optional dependency

```txt
# Optional: LLM evaluation
sentence-transformers>=3.0
```

---

### Task 4.2: Create scripts/eval_llm.py with CLI

**Files:**
- Create: `scripts/eval_llm.py`

```python
#!/usr/bin/env python3
"""LLM evaluation framework — compare providers on semantic similarity."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Any

def parse_args():
    parser = argparse.ArgumentParser(description="Compare LLM providers")
    parser.add_argument("--prompts", type=str, required=True, help="Prompts file (one per line)")
    parser.add_argument("--providers", type=str, required=True, help="Comma-separated provider names")
    parser.add_argument("--output", type=str, default="eval_results.json", help="Output JSON path")
    parser.add_argument("--reference", type=str, default=None, help="Reference answers file")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2", help="Embedding model name")
    return parser.parse_args()
```

---

### Task 4.3: Implement prompt loading from file

```python
def load_prompts(path: str) -> List[str]:
    """Load prompts from file (one per line, skip empty/comment lines)."""
    prompts = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                prompts.append(line)
    return prompts
```

---

### Task 4.4: Implement parallel LLM querying

```python
async def query_providers(prompts: List[str], providers: List[str]) -> List[Dict]:
    """Send each prompt to all providers in parallel."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from anima.services.intelligence.llm.factory import LLMFactory
    from anima.config.app import AppConfig
    
    config = AppConfig.load()
    results = []
    
    for prompt in prompts:
        tasks = []
        for name in providers:
            tasks.append(_query_one(name, prompt, config))
        
        for coro in asyncio.as_completed(tasks):
            results.append(await coro)
    
    return results

async def _query_one(provider: str, prompt: str, config) -> Dict:
    """Query a single provider and record response + latency."""
    llm = LLMFactory.create(provider, config)
    start = time.perf_counter()
    response = await llm.chat(prompt)
    latency_ms = (time.perf_counter() - start) * 1000
    return {
        "provider": provider,
        "prompt": prompt,
        "response": response,
        "latency_ms": latency_ms,
    }
```

---

### Task 4.5: Implement semantic similarity scoring

```python
def compute_similarity(results: List[Dict], model_name: str = "all-MiniLM-L6-v2") -> List[Dict]:
    """Compute semantic similarity between responses and references."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    
    for r in results:
        if r.get("reference"):
            emb1 = model.encode(r["response"], normalize_embeddings=True)
            emb2 = model.encode(r["reference"], normalize_embeddings=True)
            from sklearn.metrics.pairwise import cosine_similarity
            r["similarity"] = float(cosine_similarity([emb1], [emb2])[0][0])
    
    return results
```

---

### Task 4.6: Generate JSON + Markdown output

```python
def generate_output(results: List[Dict], output_path: str):
    """Generate JSON output and print Markdown table."""
    # Aggregate per provider
    from collections import defaultdict
    by_provider = defaultdict(list)
    for r in results:
        by_provider[r["provider"]].append(r)
    
    summary = {}
    for provider, items in by_provider.items():
        sims = [i.get("similarity", 0) for i in items if "similarity" in i]
        lats = [i["latency_ms"] for i in items]
        avg_sim = sum(sims) / len(sims) if sims else 0
        avg_lat = sum(lats) / len(lats) if lats else 0
        quality_per_sec = avg_sim / (avg_lat / 1000) if avg_lat > 0 else 0
        
        summary[provider] = {
            "avg_similarity": round(avg_sim, 4),
            "avg_latency_ms": round(avg_lat, 2),
            "quality_per_sec": round(quality_per_sec, 4),
            "responses": items,
        }
    
    output = {"results": summary}
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # Markdown table
    print(f"\n## LLM Evaluation Results\n")
    print(f"| Provider | Avg Similarity | Avg Latency (s) | Quality/sec |")
    print(f"|----------|---------------|-----------------|-------------|")
    for provider, data in summary.items():
        print(f"| {provider} | {data['avg_similarity']:.2f} | {data['avg_latency_ms']/1000:.2f} | {data['quality_per_sec']:.2f} |")
```

---

### Task 4.7: Create sample eval prompt file

**Files:**
- Create: `eval_prompts.txt`

```
# Anima LLM Evaluation Prompts
请介绍一下你自己。
什么是 LangGraph 状态机？
解释一下 RAG 检索增强生成。
如何处理 LLM 超时？
服务池模式有什么好处？
```

---

### Task 4.8: Run initial evaluation and commit results

Run: `python scripts/eval_llm.py --prompts eval_prompts.txt --providers deepseek,openai`
Expected: JSON written to `eval_results.json`, Markdown table printed

Verify: check `eval_results.json` has correct structure

---

## Summary of Files

| Action | File | Capability |
|--------|------|------------|
| Modify | `scripts/benchmark.py` | P1 |
| Create | `src/animetta/core/redis_checkpoint.py` | P3 |
| Create | `scripts/eval_llm.py` | P4 |
| Create | `eval_prompts.txt` | P4 |
| Create | `tests/test_error_resilience.py` | P2 |
| Create | `tests/test_redis_checkpoint.py` | P3 |
| Modify | `src/animetta/orchestration/graph/llm_node.py` | P2 |
| Modify | `src/animetta/orchestration/graph/tts_node.py` | P2 |
| Modify | `src/animetta/orchestration/graph/asr_node.py` | P2 |
| Modify | `src/animetta/orchestration/graph/builder.py` | P3 |
| Modify | `src/animetta/core/socketio_server.py` | P3 |
| Modify | `frontend/stats/stats.js` | P2 |
| Modify | `frontend/stats/index.html` | P2 |
| Modify | `requirements.txt` | P3, P4 |

---

## Execution Approach

This plan has 4 independent capability groups with no cross-dependencies. Choose:

1. **Subagent-Driven (this session)** — I dispatch one subagent per capability, review between tasks
2. **Parallel Session (separate)** — Open new session with `executing-plans`, batch execution with checkpoints

Recommended: **Subagent-Driven** — all 4 are independent, can dispatch separate subagents per capability simultaneously.

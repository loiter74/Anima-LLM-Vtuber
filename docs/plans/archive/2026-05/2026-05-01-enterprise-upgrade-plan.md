# Enterprise-Grade Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Anima into an enterprise-grade AI companion framework suitable for job-seeking portfolio.

**Architecture:** Three-layer progression — infrastructure (test/CI/type safety) → AI capability (LangGraph/memory/tools) → delivery (containerization/docs/deploy). Each layer leaves the project in a shippable state.

**Tech Stack:** Python 3.13, FastAPI, Socket.IO, LangGraph, LangChain, Pydantic V2, pytest, mypy, ruff, Docker, GitHub Actions, Chroma, SQLite FTS5

---

## Layer 1: Infrastructure (Week 1-2)

### Task 1.1: Configure pytest with asyncio and coverage

**Files:**
- Create: `pyproject.toml` (if not exists, add [tool.pytest.ini_options])
- Modify: `.github/workflows/test.yml`

**Step 1: Add pytest config to pyproject.toml**

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "asyncio: mark test as asyncio",
    "integration: mark as integration test (requires external services)",
]
addopts = "-v --tb=short"
```

**Step 2: Install coverage dependency**

Run: `pip install pytest-cov`

**Step 3: Verify existing tests still pass**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -m pytest tests/ -v`
Expected: 28 passed

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: configure pytest with asyncio mode and coverage"
```

---

### Task 1.2: Create conftest.py with shared mock fixtures

**Files:**
- Create: `tests/conftest.py`

**Step 1: Write conftest.py**

```python
"""Global test fixtures for Anima tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import AsyncGenerator

@pytest.fixture
def mock_llm():
    """Mock LLM service that returns predictable responses."""
    mock = AsyncMock()
    mock.chat_stream = AsyncMock()
    async def _stream():
        yield "mock response chunk"
    mock.chat_stream.return_value = _stream()
    mock.close = AsyncMock()
    return mock

@pytest.fixture
def mock_tts():
    """Mock TTS service."""
    mock = AsyncMock()
    mock.synthesize = AsyncMock(return_value=b"mock_audio_data")
    mock.close = AsyncMock()
    return mock

@pytest.fixture
def mock_asr():
    """Mock ASR service."""
    mock = AsyncMock()
    mock.transcribe = AsyncMock(return_value="mock transcription")
    mock.close = AsyncMock()
    return mock

@pytest.fixture
def mock_vad():
    """Mock VAD service."""
    mock = AsyncMock()
    mock.is_speech = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    return mock

@pytest.fixture
def mock_socketio():
    """Mock Socket.IO server for testing event emission."""
    mock = MagicMock()
    mock.emit = MagicMock()
    mock.enter_room = MagicMock()
    mock.leave_room = MagicMock()
    return mock

@pytest.fixture
def mock_service_context(mock_llm, mock_tts, mock_asr, mock_vad):
    """Create a ServiceContext with all services mocked."""
    from unittest.mock import MagicMock
    ctx = MagicMock()
    ctx.llm_engine = mock_llm
    ctx.tts_engine = mock_tts
    ctx.asr_engine = mock_asr
    ctx.vad_engine = mock_vad
    ctx.emotion_analyzer = MagicMock()
    ctx.emotion_analyzer.analyze = MagicMock(return_value="neutral")
    ctx.memory_system = MagicMock()
    ctx.memory_system.query = AsyncMock(return_value=[])
    return ctx
```

**Step 2: Run existing tests to verify conftest doesn't break anything**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -m pytest tests/ -v`
Expected: 28 passed (same as before)

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared mock fixtures for all external services"
```

---

### Task 1.3: Create GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/test.yml`

**Step 1: Write test workflow**

```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.13"]

    steps:
    - uses: actions/checkout@v4
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest-cov mypy ruff
    - name: Lint with ruff
      run: ruff check src/ tests/
    - name: Type check with mypy
      run: mypy src/ --ignore-missing-imports || true
    - name: Test with pytest
      run: |
        PYTHONPATH=src python -m pytest tests/ -v --cov=src/anima --cov-report=term-missing --cov-fail-under=0
    - name: Build check
      run: python -c "import anima; print('Import OK')"
```

**Step 2: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow"
```

---

### Task 1.4: Add ruff and mypy configuration

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add ruff config**

```toml
[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "SIM"]

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.13"
strict = false
warn_unused_configs = true
ignore_missing_imports = true
disallow_untyped_defs = false
disallow_any_unimported = false

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```

**Step 2: Run ruff check**

Run: `ruff check src/`
Expected: Clean or minimal warnings

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add ruff and mypy configuration"
```

---

### Task 1.5: Fix Pydantic V2 deprecation warnings

**Files:**
- Modify: `src/animetta/config/core/base.py`
- Modify: `src/animetta/config/providers/llm/local_lora_llm.py`
- Check: any other files using `class Config:`

**Step 1: Fix base.py**

In `src/animetta/config/core/base.py`, replace `class Config:` with `model_config`:

```python
from pydantic import ConfigDict

class BaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... rest of class

class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... rest of class
```

**Step 2: Fix local_lora_llm.py**

Same pattern: replace `class Config:` with `model_config = ConfigDict(...)`.

**Step 3: Check for other occurrences**

Run: `grep -rn "class Config:" src/animetta/ --include="*.py"`
If any remain, fix them with the same pattern.

**Step 4: Run tests to verify**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -m pytest tests/ -v -W error::pytest.PytestDeprecationWarning 2>&1 | grep -i "deprecation\|warning"`
Expected: Zero Pydantic V2 deprecation warnings

**Step 5: Commit**

```bash
git add src/animetta/config/core/base.py src/animetta/config/providers/llm/local_lora_llm.py
git commit -m "fix: migrate Pydantic V2 class Config to model_config"
```

---

### Task 1.6: Write TESTING.md

**Files:**
- Create: `TESTING.md`

**Step 1: Write TESTING.md**

See `TESTING.md` content in design doc. Cover:
- Philosophy: "100% test coverage makes vibe coding safe"
- How to run: pytest, coverage, asyncio mode
- Test layers: Unit (mock all externals), Integration (real DB/file), E2E (full stack)
- Conventions: file naming, fixtures in conftest, AAA pattern

**Step 2: Add README section linking to TESTING.md**

Append to README:
```markdown
## Testing

See [Testing Guide](../../../development/testing.md) for test philosophy, how to run tests, and coverage targets.
```

**Step 3: Commit**

```bash
git add TESTING.md README.md
git commit -m "docs: add TESTING.md with test philosophy and conventions"
```

---

### Task 1.7: Add CI badge to README

**Files:**
- Modify: `README.md`

**Step 1: Add badge at top of README**

```markdown
<div align="center">

![CI](https://github.com/loiter74/Anima-LLM-Vtuber/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

</div>
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add CI badge and version badges to README"
```

---

## Layer 2: AI Capability (Week 3-6)

### Task 2.1: Write llm_node tests

**Files:**
- Create: `tests/orchestration/graph/test_llm_node.py`

**Step 1: Write test file**

Test cases:
1. `test_llm_node_with_text` — mock LLM returns a response, verify state updated
2. `test_llm_node_with_tools` — mock LLM returns tool_calls, verify tool_results populated
3. `test_llm_node_empty_input` — empty user_text, verify graceful handling
4. `test_llm_node_rag_context` — verify memory context is injected into prompt
5. `test_llm_node_error_recovery` — LLM raises exception, verify error in state

```python
"""Tests for LangGraph LLM node."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langgraph.graph import RunnableConfig

from anima.orchestration.graph.state import AgentState


@pytest.fixture
def base_state():
    return {
        "input_type": "text",
        "user_text": "你好",
        "messages": [],
        "session_id": "test-session",
        "response_text": "",
        "tool_calls": None,
        "tool_results": None,
    }


@pytest.mark.asyncio
async def test_llm_node_with_text(base_state, mock_service_context):
    """LLM node processes text and updates response_text."""
    from anima.orchestration.graph.llm_node import llm_node

    state = {**base_state, "_config": {"service_context": mock_service_context}}

    config = RunnableConfig()
    result = await llm_node(state, config)

    assert "response_text" in result
    assert len(result["response_text"]) > 0


# Additional test cases follow same pattern...
```

**Step 2: Run test**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -m pytest tests/orchestration/graph/test_llm_node.py -v`
Expected: 5 passed

**Step 3: Commit**

```bash
git add tests/orchestration/graph/test_llm_node.py
git commit -m "test: add LLM node unit tests (5 cases)"
```

---

### Task 2.2: Write tts_node tests

**Files:**
- Create: `tests/orchestration/graph/test_tts_node.py`

Test cases:
1. `test_tts_node_with_response` — response_text present, mock TTS returns audio
2. `test_tts_node_empty_response` — empty response_text, skip TTS
3. `test_tts_node_error` — TTS raises exception, graceful handling
4. `test_tts_node_audio_format` — verify audio format in output state

---

### Task 2.3: Write emotion_node tests

**Files:**
- Create: `tests/orchestration/graph/test_emotion_node.py`

Test cases:
1. `test_emotion_node_with_text` — emotion extracted from response_text
2. `test_emotion_node_default` — no response_text, returns default emotion
3. `test_emotion_node_analyzer_error` — analyzer fails, graceful fallback

---

### Task 2.4: Write output_node tests

**Files:**
- Create: `tests/orchestration/graph/test_output_node.py`

Test cases:
1. `test_output_node_sends_events` — verify Socket.IO events emitted
2. `test_output_node_stores_memory` — verify memory system called
3. `test_output_node_empty_state` — minimal state, no crash

---

### Task 2.5: Write orchestrator integration tests

**Files:**
- Create: `tests/orchestration/graph/test_orchestrator.py`

Test cases:
1. `test_process_text` — full text processing flow with mocks
2. `test_process_audio` — audio processing flow with mocks
3. `test_orchestrator_creation` — factory creates properly
4. `test_orchestrator_with_tools` — tool-enabled flow
5. `test_orchestrator_error_handling` — LLM error propagates correctly

---

### Task 2.6: Write MCP bridge graceful degradation

**Files:**
- Modify: `src/animetta/tools/mcp_bridge.py`

**Step 1: Change Docker failure from ERROR to WARNING**

Find the Docker connection error in `mcp_bridge.py` and change:
```python
logger.error(f"[MCP:{name}] 连接失败: {e}")
```
to:
```python
logger.warning(f"[MCP:{name}] Docker 不可用，跳过: {e}")
```

**Step 2: Verify the change**

Run: `cd /c/Users/30262/Project/Anima && PYTHONPATH=src python -c "from anima.tools.mcp_bridge import MCPBridge; print('Import OK')"`
Expected: No errors (warning about Docker is expected)

**Step 3: Write test**

Create `tests/tools/test_mcp_bridge.py`:
```python
"""Tests for MCP bridge with Docker unavailable."""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_mcp_bridge_docker_unavailable():
    """MCP bridge should warn and continue when Docker is not available."""
    from anima.tools.mcp_bridge import MCPBridge
    bridge = MCPBridge(name="test", transport="stdio",
                       command="echo", args=["hello"])
    result = await bridge.connect()
    assert result is False  # Should not crash
```

---

### Task 2.7: Write memory chunker tests

**Files:**
- Create: `tests/memory/test_chunker.py`

Test cases:
1. `test_chunker_basic` — simple markdown, verify chunks returned
2. `test_chunker_window_overlap` — overlapping windows contain shared content
3. `test_chunker_empty_document` — empty string returns empty list
4. `test_chunker_single_short` — content shorter than chunk size returns single chunk

---

### Task 2.8: Write hybrid search tests

**Files:**
- Create: `tests/memory/test_hybrid_search.py`

Test cases:
1. `test_hybrid_search_vector_weight` — vector (70%) dominates results
2. `test_hybrid_search_keyword_weight` — BM25 (30%) contributes
3. `test_hybrid_search_empty` — no results returns empty list
4. `test_hybrid_search_score_range` — scores normalized to 0-1

---

### Task 2.9: Register stats_api routes on main ASGI app

**Files:**
- Modify: `src/animetta/core/socketio_server.py` or the ASGI app setup

**Step 1: Find where the ASGI app is created**

Search for `FastAPI()` or `ASGIApp` in the server setup code.

**Step 2: Add stats_api router**

```python
from anima.orchestration.server.stats_api import router as stats_router

# In the app creation:
app.include_router(stats_router, prefix="/api")
```

**Step 3: Test the endpoint**

Run: `curl http://localhost:12394/api/stats/overview`
Expected: 200 with JSON response

---

### Task 2.10: Add /health endpoint

**Files:**
- Modify: `src/animetta/orchestration/server/routes.py` or appropriate file

**Step 1: Create health check function**

```python
from fastapi import APIRouter

health_router = APIRouter()

@health_router.get("/health")
async def health_check():
    """Unified health check endpoint."""
    return {
        "status": "ok",
        "services": {
            "server": "running",
            "timestamp": time.time(),
        }
    }
```

**Step 2: Register on main app**

```python
app.include_router(health_router)
```

**Step 3: Test**

Run: `curl http://localhost:12394/health`
Expected: `{"status": "ok", ...}`

---

### Task 2.11: Write .env.example

**Files:**
- Create: `.env.example`

List all environment variables with types, descriptions, and examples:
```bash
# === LLM Providers ===
# GLM (Zhipu AI)
GLM_API_KEY=your_api_key_here

# OpenAI-compatible (DeepSeek, OpenAI, etc.)
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://api.deepseek.com/v1

# === Service Selection ===
ANIMA_LLM=deepseek         # deepseek, glm, openai, ollama, local_lora
ANIMA_TTS=vibe_voice       # vibe_voice, edge, glm, openai, chattts, mock
ANIMA_ASR=faster_whisper   # faster_whisper, glm, openai, funasr, mock

# === Paths ===
ANIMA_BASE_MODEL_PATH=./models
ANIMA_LORA_PATH=./loras

# === Server ===
ANIMA_HOST=0.0.0.0
ANIMA_PORT=12394
ANIMA_LOG_LEVEL=INFO
```

---

## Layer 3: Delivery (Week 7-8)

### Task 3.1: Create Dockerfile

**Files:**
- Create: `Dockerfile`

```dockerfile
# Stage 1: Build
FROM python:3.13-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Run
FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY src/ src/
COPY config/ config/
COPY scripts/ scripts/

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app/src

EXPOSE 12394
CMD ["python", "-m", "anima.core.socketio_server"]
```

---

### Task 3.2: Create docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

```yaml
version: "3.8"
services:
  backend:
    build: .
    ports:
      - "12394:12394"
    environment:
      - ANIMA_HOST=0.0.0.0
      - ANIMA_PORT=12394
      - ANIMA_LOG_LEVEL=INFO
    volumes:
      - ./memory_db:/app/memory_db
      - ./data:/app/data
      - ./.env:/app/.env
    restart: unless-stopped
```

---

### Task 3.3: Write ARCHITECTURE.md

**Files:**
- Create: `ARCHITECTURE.md`

Cover:
- System overview with Mermaid diagram
- Data flow: User Input → LangGraph → Output
- Module directory map (accurate, not stale)
- LangGraph state machine visualization
- Configuration layering
- Memory system architecture

---

### Task 3.4: Rewrite README.md

**Files:**
- Modify: `README.md`

Reorganize:
1. Demo GIF + badges at top
2. One-liner: what is Anima
3. Architecture diagram (ASCII or Mermaid)
4. Quick start (3 commands)
5. Feature highlights with screenshots
6. Tech stack table
7. Project structure (accurate)
8. Links to ARCHITECTURE.md, TESTING.md, CONTRIBUTING.md

---

### Task 3.5: Deploy demo to Fly.io

**Files:**
- Create: `fly.toml`

```toml
app = "anima-demo"

[build]
  dockerfile = "Dockerfile"

[[services]]
  internal_port = 12394
  protocol = "tcp"

  [[services.ports]]
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls"]
    port = 443

  [[services.concurrency]]
    hard_limit = 25
    soft_limit = 10
```

**Deploy steps:**
1. `flyctl launch`
2. `flyctl secrets set GLM_API_KEY=...`
3. `flyctl deploy`
4. Verify: `curl https://anima-demo.fly.dev/health`

---

### Task 3.6: Translate Chinese comments to English

**Files:** All `src/animetta/*.py`

Run: `grep -rn "[\u4e00-\u9fff]" src/animetta/ --include="*.py"` to find all Chinese comments, then translate each to English.

Focus areas:
- `src/animetta/orchestration/server/routes.py` — heavy Chinese logging
- `src/animetta/core/service_context.py` — Chinese log messages
- `src/animetta/config/` — Chinese docstrings

---

### Task 3.7: Clean up stale files

- Remove `__pycache__` directories from git tracking
- Remove backup files
- Update `.gitignore` with comprehensive entries
- Clean up `TODOS.md`
- Verify `docs/` only contains current architecture docs

---

## Quick Reference: Full Task List

```
Week 1 — Infrastructure
  [ ] 1.1 Configure pytest (pyproject.toml, coverage)
  [ ] 1.2 Create conftest.py (shared mocks)
  [ ] 1.3 GitHub Actions test workflow
  [ ] 1.4 ruff + mypy config
  [ ] 1.5 Fix Pydantic V2 deprecations
  [ ] 1.6 Write TESTING.md
  [ ] 1.7 Add CI badge to README

Week 2 — AI Capability Start
  [ ] 2.1 llm_node tests (5 cases)
  [ ] 2.2 tts_node tests (4 cases)
  [ ] 2.3 emotion_node tests (3 cases)
  [ ] 2.4 output_node tests (3 cases)
  [ ] 2.5 orchestrator integration tests (5 cases)
  [ ] 2.6 MCP bridge graceful degradation + test

Week 3 — Memory + Tools
  [ ] 2.7 Memory chunker tests (4 cases)
  [ ] 2.8 Hybrid search tests (4 cases)
  [ ] 2.9 Register stats_api routes
  [ ] 2.10 Add /health endpoint
  [ ] 2.11 Write .env.example

Week 4 — Delivery
  [ ] 3.1 Dockerfile
  [ ] 3.2 docker-compose.yml
  [ ] 3.3 ARCHITECTURE.md
  [ ] 3.4 README rewrite
  [ ] 3.5 Fly.io deploy config
  [ ] 3.6 Translate Chinese comments
  [ ] 3.7 Clean up stale files
```

**Total: ~30 tasks, estimated ~8 weeks part-time.**

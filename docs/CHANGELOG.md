# Anima Project Changelog

## [Unreleased]

### Added - 2026-03-02

#### Three-Layer Memory System
Implemented a comprehensive three-layer memory system for cross-session conversation persistence.

**Architecture**:
- **Short-term Memory**: Session-based in-memory storage (deque, 20-turn capacity)
- **Long-term Memory**: SQLite persistent storage with full-text search (FTS5)
- **Importance Scorer**: Multi-factor evaluation (length, emotion, questions, keywords)

**Files Added**:
- `src/anima/memory/__init__.py` - Module exports
- `src/anima/memory/memory_turn.py` - Data models (MemoryTurn, Entity, Relation)
- `src/anima/memory/short_term.py` - Session-based memory with auto-cleanup
- `src/anima/memory/long_term.py` - SQLite persistence with FTS
- `src/anima/memory/importance_scorer.py` - Multi-factor importance evaluation
- `src/anima/memory/memory_system.py` - Unified coordinator API
- `config/features/memory.yaml` - Memory system configuration
- `scripts/init_memory_db.py` - Database initialization script
- `docs/memory-system/ARCHITECTURE.md` - Architecture documentation
- `docs/memory-system/INTEGRATION.md` - Integration guide
- `tests/test_memory_integration.py` - Integration tests

**Modified Files**:
- `src/anima/service_context.py`
  - Added `memory_system` field
  - Added `init_memory()` method
  - Integrated into `load_from_config()` and `close()`

- `src/anima/services/conversation/orchestrator.py`
  - Added `memory_system` parameter to `__init__()`
  - Added memory retrieval before LLM call in `_process_conversation()`
  - Added memory storage after response generation
  - Added `_format_memory_context()` helper method

- `src/anima/socketio_server.py`
  - Pass `memory_system` to ConversationOrchestrator

- `.gitignore`
  - Added `.claude/skills/` (user-specific skills)
  - Added `data/*.db` (user-specific databases)

**Features**:
- **Automatic Memory Retrieval**: Before each conversation, relevant memories are retrieved and injected into the context
- **Automatic Memory Storage**: After each conversation, the turn is stored with importance evaluation
- **Intelligent Routing**: High-importance conversations (≥0.7) go to long-term storage, low-importance stay in short-term
- **Full-Text Search**: SQLite FTS5 enables fast text-based retrieval
- **Session Isolation**: Each session has separate memory space

**Configuration** (`config/features/memory.yaml`):
```yaml
memory:
  enabled: true
  short_term:
    max_turns: 20
  long_term:
    backend: sqlite
    db_path: data/memories.db
  importance:
    threshold: 0.7
    base_score: 0.5
```

**API Usage**:
```python
from anima.memory import MemorySystem, MemoryTurn

# Initialize
memory = MemorySystem(config)

# Store conversation
await memory.store_turn(memory_turn)

# Retrieve relevant memories
memories = await memory.retrieve_context(
    query="user query",
    session_id="session_123",
    max_turns=5
)

# Get user history
history = await memory.get_user_history(
    session_id="session_123",
    limit=50
)
```

**Testing**:
- All integration tests pass ✅
- Test suite: `tests/test_memory_integration.py`
- Run with: `python tests/test_memory_integration.py`

**Performance**:
- Short-term memory: O(1) access (deque)
- Long-term search: O(log n) with FTS5 indexes
- Memory overhead: ~1KB per conversation turn

**Known Limitations**:
1. Vector embeddings not implemented (currently uses FTS5 text search)
2. Knowledge graph not implemented (Entity/Relation structures defined but unused)
3. Importance scoring is rule-based (could upgrade to ML model)

#### Project Optimization Report
- `docs/OPTIMIZATION_REPORT.md` - Comprehensive analysis using 7 agent skills
  - Context compression recommendations
  - Multi-agent architecture patterns
  - Frontend performance optimization
  - Evaluation framework design

### Changed
- Updated `.gitignore` to exclude user-specific files

### Removed
- `config/mcporter.json` - Temporary configuration file
- `install.md` - Agent Reach installation documentation (not project-specific)

---

## Previous Releases

See git history for earlier changes.

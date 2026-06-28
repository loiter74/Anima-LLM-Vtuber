# Testing Guide

## Philosophy

100% test coverage is the key to great vibe coding. Tests let you move fast,
trust your instincts, and ship with confidence — without them, vibe coding is
just yolo coding. With tests, it's a superpower.

## How to Run Tests

```bash
# Run all tests (from project root)
PYTHONPATH=src python -m pytest tests/

# With coverage report
PYTHONPATH=src python -m pytest tests/ --cov=src/animetta --cov-report=term-missing

# Run a specific test file
PYTHONPATH=src python -m pytest tests/test_main_path.py -v

# Run a specific test class
PYTHONPATH=src python -m pytest tests/test_stats_store.py::TestStatsStore -v

# Run a specific test
PYTHONPATH=src python -m pytest tests/test_main_path.py::TestVADServicesRegistered::test_vad_services_registered -v
```

## Test Framework

- **pytest** with `asyncio_mode = auto` (async tests work without extra decorators)
- **pytest-cov** for coverage measurement
- Shared fixtures in `tests/conftest.py`

## Test Layers

| Layer | What | Where | Externals |
|-------|------|-------|-----------|
| Unit | Individual functions, classes | `tests/` | All mocked |
| Integration | Multi-component flows | `tests/` | Real DB/files |
| E2E | Full pipeline via Socket.IO | `tests/e2e/` | Real services |

### Unit Tests

- All external services (LLM, TTS, ASR, VAD, Socket.IO) **must be mocked**
- Use fixtures from `tests/conftest.py` rather than creating mocks inline
- Follow the Arrange-Act-Assert (AAA) pattern
- Test both happy paths and error paths

### Mock Fixtures

Available shared mocks in `conftest.py`:

| Fixture | Mocks | Key Methods |
|---------|-------|-------------|
| `mock_llm` | LLM service | `chat_stream()`, `close()` |
| `mock_tts` | TTS service | `synthesize()`, `close()` |
| `mock_asr` | ASR service | `transcribe()`, `close()` |
| `mock_vad` | VAD service | `is_speech()`, `process_audio()`, `close()` |
| `mock_socketio` | Socket.IO server | `emit()`, `enter_room()`, `leave_room()` |
| `mock_service_context` | Full service container | Composes all above mocks |

## Conventions

- **File naming**: `test_<module_name>.py`
- **Class naming**: `Test<ComponentName>`
- **Method naming**: `test_<behavior>`
- **Assertions**: Use plain `assert` statements (not `self.assert*`)
- **Async tests**: Functions declared with `async def` — pytest handles the event loop
- **Fixtures**: Use `conftest.py` for shared fixtures, test-file-local fixtures for specific setup

## Coverage Target

| Milestone | Target | Status |
|-----------|--------|--------|
| Current | 21% | ⬜ |
| Layer 1 | 30% | ⬜ |
| Layer 2 | 60% | ⬜ |
| Goal | 70%+ | ⬜ |

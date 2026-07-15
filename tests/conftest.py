from __future__ import annotations

"""Global test fixtures and configuration for Anima tests."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# ── Shared Mock Fixtures ─────────────────────────────────────────


@pytest.fixture
def mock_llm():
    """Mock LLM service returning canned responses."""
    mock = MagicMock()
    mock.chat_stream = AsyncMock()

    async def _stream():
        yield "mock response chunk"

    mock.chat_stream.return_value = _stream()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_tts():
    """Mock TTS service returning dummy audio bytes."""
    mock = MagicMock()
    mock.synthesize = AsyncMock(return_value=b"mock_audio_data")
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_asr():
    """Mock ASR service returning canned transcription."""
    mock = MagicMock()
    mock.transcribe = AsyncMock(return_value="mock transcription text")
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_vad():
    """Mock VAD service always detecting speech."""
    mock = MagicMock()
    mock.is_speech = AsyncMock(return_value=True)
    mock.process_audio = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_socketio():
    """Mock Socket.IO server for testing event emission."""
    mock = MagicMock()
    mock.emit = AsyncMock()
    mock.enter_room = AsyncMock()
    mock.leave_room = AsyncMock()
    return mock


@pytest.fixture
def mock_service_context(mock_llm, mock_tts, mock_asr, mock_vad):
    """Create a ServiceContext with all external services mocked."""
    ctx = MagicMock()
    ctx.llm_engine = mock_llm
    ctx.tts_engine = mock_tts
    ctx.asr_engine = mock_asr
    ctx.vad_engine = mock_vad
    ctx.emotion_analyzer = MagicMock()
    ctx.emotion_analyzer.analyze = MagicMock(return_value="neutral")
    ctx.memory_system = MagicMock()
    ctx.memory_system.query = AsyncMock(return_value=[])
    ctx.memory_system.store_turn = AsyncMock()
    ctx.memory_system.retrieve_context = AsyncMock(return_value=[])
    ctx.close = AsyncMock()
    return ctx


# ── Extended Mock Fixtures ──────────────────────────────────


@pytest.fixture
def mock_embedding():
    """Mock sentence-transformer embedding model returning fixed vector."""
    mock = MagicMock()
    mock.encode = MagicMock(return_value=[0.1] * 384)
    return mock


@pytest.fixture
def mock_chroma():
    """Mock ChromaDB client with in-memory store."""
    mock = MagicMock()
    mock_collection = MagicMock()
    mock_collection.add = MagicMock()
    mock_collection.query = MagicMock(
        return_value={"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}
    )
    mock_collection.delete = MagicMock()
    mock_collection.upsert = MagicMock()
    mock_collection.count = MagicMock(return_value=0)
    mock.get_or_create_collection = MagicMock(return_value=mock_collection)
    mock.delete_collection = MagicMock()
    mock.heartbeat = MagicMock(return_value=1)
    return mock


@pytest.fixture
def mock_mcp_client():
    """Mock MCP client that returns predefined tools."""
    mock = MagicMock()
    mock.list_tools = AsyncMock(return_value=[])
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()

    async def _mock_call_tool(name, args):
        return MagicMock(content=[MagicMock(text=f"executed {name}")])

    mock.call_tool = _mock_call_tool
    return mock


@pytest.fixture
def mock_minecraft_bridge():
    """Mock Minecraft bridge that simulates bot connection."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.send_command = AsyncMock(return_value={"success": True, "result": "done"})
    mock.get_status = MagicMock(
        return_value={"connected": True, "position": {"x": 0, "y": 64, "z": 0}}
    )
    return mock


@pytest.fixture
def mock_bilibili_client():
    """Mock Bilibili danmaku client."""
    mock = MagicMock()
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.is_connected = MagicMock(return_value=False)
    mock.on_danmaku = MagicMock()
    return mock

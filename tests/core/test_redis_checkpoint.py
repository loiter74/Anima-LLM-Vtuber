from __future__ import annotations

"""Tests for AsyncRedisSaver — Redis-backed LangGraph checkpoint persistence."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.base import CheckpointTuple

from animetta.core.redis_checkpoint import AsyncRedisSaver

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    """Patch redis.asyncio.from_url and return a mock Redis instance."""
    with patch("redis.asyncio.from_url") as mock_from_url:
        instance = AsyncMock()
        mock_from_url.return_value = instance
        yield instance


@pytest.fixture
def saver(mock_redis):
    """Create AsyncRedisSaver with a fully mocked Redis connection."""
    return AsyncRedisSaver(redis_url="redis://localhost:6379/0")


# ── Helpers ────────────────────────────────────────────────────────


def _make_minimal_checkpoint() -> dict:
    return {"id": "test-cid-001", "ts": "2025-01-01T00:00:00Z"}


def _make_minimal_config(thread_id: str = "thread-1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ── __init__ ───────────────────────────────────────────────────────


class TestInit:
    """Verify constructor sets up the Redis connection correctly."""

    def test_creates_redis_connection(self):
        """Should create a Redis connection with the given URL and 5s timeout."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_instance = AsyncMock()
            mock_from_url.return_value = mock_instance

            saver = AsyncRedisSaver(redis_url="redis://myhost:7777/1")

            mock_from_url.assert_called_once_with(
                "redis://myhost:7777/1",
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            assert saver._redis_url == "redis://myhost:7777/1"
            assert saver._prefix == "checkpoint:"
            assert saver._writes_prefix == "checkpoint_writes:"
            assert saver.redis is mock_instance


# ── _serialize ─────────────────────────────────────────────────────


class TestSerialize:
    """Unit tests for _serialize static method."""

    def test_handles_dict(self):
        """_serialize should convert a dict to a JSON string."""
        data = {"key": "value", "num": 42}
        result = AsyncRedisSaver._serialize(data)
        assert json.loads(result) == data

    def test_handles_nested_structures(self):
        """_serialize should handle nested dicts and lists."""
        data = {"a": [1, {"b": "c"}], "d": None}
        result = AsyncRedisSaver._serialize(data)
        assert json.loads(result) == data

    def test_falls_back_to_str_for_non_serializable(self):
        """_serialize should use str() fallback for non-serializable objects."""

        class Custom:
            def __str__(self):
                return "custom_str"

        result = AsyncRedisSaver._serialize({"obj": Custom()})
        parsed = json.loads(result)
        assert parsed["obj"] == "custom_str"


# ── _deserialize ───────────────────────────────────────────────────


class TestDeserialize:
    """Unit tests for _deserialize static method."""

    def test_handles_bytes(self):
        """_deserialize should convert bytes to a dict."""
        raw = b'{"key": "value", "num": 42}'
        result = AsyncRedisSaver._deserialize(raw)
        assert result == {"key": "value", "num": 42}

    def test_handles_empty_dict(self):
        """_deserialize should handle empty dict bytes."""
        raw = b"{}"
        result = AsyncRedisSaver._deserialize(raw)
        assert result == {}

    def test_handles_unicode(self):
        """_deserialize should handle unicode content."""
        raw = '{"hello": "世界"}'.encode()
        result = AsyncRedisSaver._deserialize(raw)
        assert result == {"hello": "世界"}


# ── _make_key ──────────────────────────────────────────────────────


class TestMakeKey:
    """Unit tests for _make_key."""

    def test_returns_prefixed_thread_id(self, saver):
        """_make_key should prefix thread_id with checkpoint:."""
        assert saver._make_key("my-thread") == "checkpoint:my-thread"

    def test_handles_empty_thread_id(self, saver):
        """_make_key should handle empty thread_id."""
        assert saver._make_key("") == "checkpoint:"


# ── _make_writes_key ──────────────────────────────────────────────


class TestMakeWritesKey:
    """Unit tests for _make_writes_key."""

    def test_returns_writes_prefixed_thread_id(self, saver):
        """_make_writes_key should prefix thread_id with checkpoint_writes:."""
        assert saver._make_writes_key("my-thread") == "checkpoint_writes:my-thread"

    def test_handles_empty_thread_id(self, saver):
        """_make_writes_key should handle empty thread_id."""
        assert saver._make_writes_key("") == "checkpoint_writes:"


# ── aget_tuple ─────────────────────────────────────────────────────


class TestAgetTuple:
    """Tests for aget_tuple — retrieving checkpoints."""

    @pytest.mark.asyncio
    async def test_returns_tuple_when_checkpoint_exists(self, saver, mock_redis):
        """Should return a CheckpointTuple when the Redis key has data."""
        checkpoint_data = {
            "checkpoint": {"id": "cid-001", "ts": "2025-01-01T00:00:00Z"},
            "metadata": {"source": "user"},
        }
        mock_redis.get.return_value = json.dumps(checkpoint_data).encode()

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert isinstance(result, CheckpointTuple)
        assert result.config["configurable"]["thread_id"] == "t1"
        assert result.checkpoint == checkpoint_data["checkpoint"]
        assert result.metadata == checkpoint_data["metadata"]
        mock_redis.get.assert_any_await("checkpoint:t1")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self, saver, mock_redis):
        """Should return None when the Redis key does not exist."""
        mock_redis.get.return_value = None

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_bytes(self, saver, mock_redis):
        """Should return None when Redis returns empty bytes (falsy)."""
        mock_redis.get.return_value = b""

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self, saver, mock_redis):
        """Should return None gracefully when Redis raises an exception."""
        mock_redis.get.side_effect = Exception("Connection refused")

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert result is None

    @pytest.mark.asyncio
    async def test_includes_pending_writes(self, saver, mock_redis):
        """Should include pending writes when the writes key exists."""
        checkpoint_data = {"checkpoint": {"id": "cid-001"}, "metadata": {}}
        writes_data = [{"channel": "messages", "value": "hello"}]
        mock_redis.get.side_effect = [
            json.dumps(checkpoint_data).encode(),
            json.dumps(writes_data).encode(),
        ]

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert result is not None
        assert result.pending_writes == writes_data

    @pytest.mark.asyncio
    async def test_no_pending_writes_when_writes_key_missing(self, saver, mock_redis):
        """Should set pending_writes to [] when the writes key is absent."""
        checkpoint_data = {"checkpoint": {"id": "cid-001"}, "metadata": {}}
        mock_redis.get.side_effect = [json.dumps(checkpoint_data).encode(), None]

        result = await saver.aget_tuple(_make_minimal_config("t1"))

        assert result is not None
        assert result.pending_writes == []


# ── aput ───────────────────────────────────────────────────────────


class TestAput:
    """Tests for aput — storing checkpoints."""

    @pytest.mark.asyncio
    async def test_stores_checkpoint_with_ttl(self, saver, mock_redis):
        """Should store serialized checkpoint data with TTL of 86400."""
        config = _make_minimal_config("t1")
        checkpoint = _make_minimal_checkpoint()
        metadata = {"source": "test"}
        new_versions = {"messages": 1}

        result = await saver.aput(config, checkpoint, metadata, new_versions)

        # Verify storage
        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        key, value = call_args[0]
        assert key == "checkpoint:t1"
        assert json.loads(value) == {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "new_versions": new_versions,
        }
        assert call_args[1] == {"ex": 86400}

        # Verify return config
        assert result["configurable"]["thread_id"] == "t1"
        assert result["configurable"]["checkpoint_id"] == "test-cid-001"

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self, saver, mock_redis):
        """Should not crash when Redis raises; still return the config."""
        mock_redis.set.side_effect = Exception("Redis down")

        result = await saver.aput(
            _make_minimal_config("t1"),
            _make_minimal_checkpoint(),
            {},
            {},
        )

        assert result["configurable"]["thread_id"] == "t1"
        assert result["configurable"]["checkpoint_id"] == "test-cid-001"


# ── aput_writes ────────────────────────────────────────────────────


class TestAputWrites:
    """Tests for aput_writes — storing pending writes."""

    @pytest.mark.asyncio
    async def test_stores_writes_with_ttl(self, saver, mock_redis):
        """Should store serialized writes with TTL of 86400."""
        writes = [{"channel": "messages", "value": "hello"}]

        await saver.aput_writes(
            _make_minimal_config("t1"), writes, task_id="task-1"
        )

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        key, value = call_args[0]
        assert key == "checkpoint_writes:t1"
        assert json.loads(value) == writes
        assert call_args[1] == {"ex": 86400}

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self, saver, mock_redis):
        """Should not crash when Redis raises during aput_writes."""
        mock_redis.set.side_effect = Exception("Redis down")

        await saver.aput_writes(
            _make_minimal_config("t1"),
            [{"channel": "x", "value": "y"}],
            task_id="task-1",
        )
        # No exception should propagate


# ── alist ──────────────────────────────────────────────────────────


class TestAlist:
    """Tests for alist — listing checkpoints (delegates to aget_tuple)."""

    @pytest.mark.asyncio
    async def test_yields_tuple_when_checkpoint_exists(self, saver, mock_redis):
        """Should yield a CheckpointTuple when aget_tuple returns one."""
        checkpoint_data = {"checkpoint": {"id": "cid-001"}, "metadata": {}}
        mock_redis.get.return_value = json.dumps(checkpoint_data).encode()

        results = [tup async for tup in saver.alist(_make_minimal_config("t1"))]

        assert len(results) == 1
        assert isinstance(results[0], CheckpointTuple)

    @pytest.mark.asyncio
    async def test_yields_nothing_when_no_checkpoint(self, saver, mock_redis):
        """Should yield nothing when aget_tuple returns None."""
        mock_redis.get.return_value = None

        results = [tup async for tup in saver.alist(_make_minimal_config("t1"))]

        assert results == []

    @pytest.mark.asyncio
    async def test_yields_nothing_when_config_is_none(self, saver):
        """Should yield nothing when config is None."""
        results = [tup async for tup in saver.alist(None)]

        assert results == []


# ── adelete_thread ─────────────────────────────────────────────────


class TestADeleteThread:
    """Tests for adelete_thread — deleting all data for a thread."""

    @pytest.mark.asyncio
    async def test_deletes_both_checkpoint_and_writes_keys(self, saver, mock_redis):
        """Should delete both the checkpoint: and checkpoint_writes: keys."""
        await saver.adelete_thread("t1")

        assert mock_redis.delete.await_count == 2
        mock_redis.delete.assert_any_await("checkpoint:t1")
        mock_redis.delete.assert_any_await("checkpoint_writes:t1")

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self, saver, mock_redis):
        """Should not crash when Redis raises during adelete_thread."""
        mock_redis.delete.side_effect = Exception("Redis down")

        await saver.adelete_thread("t1")
        # No exception should propagate


# ── close ──────────────────────────────────────────────────────────


class TestClose:
    """Tests for close — closing the Redis connection."""

    @pytest.mark.asyncio
    async def test_closes_redis_connection(self, saver, mock_redis):
        """Should call aclose() on the Redis connection."""
        await saver.close()

        mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self, saver, mock_redis):
        """Should not crash when Redis raises during close."""
        mock_redis.aclose.side_effect = Exception("Close failed")

        await saver.close()
        # No exception should propagate

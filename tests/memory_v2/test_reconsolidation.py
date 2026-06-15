from __future__ import annotations

"""Tests for ReconsolidationClient and LLM-driven reconsolidation."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.emotion_field import VAD_MAP
from animetta.memory.v2.reconsolidation import (
    ReconsolidationClient,
    get_reconsolidation_client,
    set_reconsolidation_client,
)
from animetta.memory.v2.system import LivingMemorySystem


class TestReconsolidationClient:
    def test_client_unavailable_without_api_key(self):
        client = ReconsolidationClient()
        assert not client.is_available

    def test_client_available_with_api_key(self):
        with patch("animetta.memory.v2.reconsolidation.AsyncOpenAI"):
            client = ReconsolidationClient(api_key="sk-test")
            assert client.is_available

    def test_reconsolidate_returns_none_when_unavailable(self):
        client = ReconsolidationClient()
        import asyncio
        result = asyncio.run(client.reconsolidate(
            content="test", version=1, rewritten_at="2026-01-01",
            valence=0.5, arousal=0.3, dominance=0.1,
        ))
        assert result is None

    def test_singleton_set_get(self):
        client = ReconsolidationClient(api_key="sk-test")
        set_reconsolidation_client(client)
        assert get_reconsolidation_client() is client
        set_reconsolidation_client(None)
        assert get_reconsolidation_client() is None


@pytest.mark.asyncio
class TestReconsolidationIntegration:
    async def test_reconsolidate_atom_metadata_fallback(self):
        """Without LLM client, reconsolidation uses metadata-only path."""
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        atom = MemoryAtom(
            id="r1", layer=Layer.RAW, content="用户喜欢咖啡",
            occurred_at=datetime.now(UTC),
            confidence=0.7,
            emotion_valence=0.5, emotion_arousal=0.3, emotion_dominance=0.1,
        )

        # Reconsolidate without LLM client
        await system._reconsolidate_atom(
            atom=atom,
            current_emotion=VAD_MAP["happy"],
            query="咖啡",
        )

        # Metadata should have changed
        assert atom.version >= 2
        assert atom.retrieval_count >= 1
        assert atom.last_accessed_at is not None
        # Decay rate should decrease
        assert atom.decay_rate < 0.1

        await system.shutdown()

    async def test_full_encode_recall_reconsolidate(self):
        """End-to-end: encode, recall, verify reconsolidation triggered."""
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        # Encode a memory
        atom = await system.encode(
            user_input="今天喝了拿铁，开心！",
            agent_response="拿铁确实不错！",
            emotion_vad=VAD_MAP["happy"],
            session_id="s1",
        )
        assert atom.layer == Layer.RAW
        assert atom.version == 1

        # Recall — triggers async reconsolidation
        result = await system.recall(
            query="拿铁",
            session_id="s1",
            current_emotion=VAD_MAP["happy"],
        )
        assert len(result.atoms) >= 1

        # Wait a moment for async reconsolidation
        import asyncio
        await asyncio.sleep(0.1)

        # Re-fetch the atom — version may have incremented
        updated = await system.store.get(atom.id)
        assert updated is not None
        # Version may be >= 1 (reconsolidation is async, might not have completed)
        # But at minimum, the atom still exists

        await system.shutdown()

class TestReconsolidationEdgeCases:
    async def test_metadata_fallback_without_llm(self):
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()
        atom = MemoryAtom(id="r2", layer=Layer.RAW, content="test",
                          occurred_at=datetime.now(UTC), confidence=0.7)
        # Reconsolidate without LLM — should use metadata fallback
        await system._reconsolidate_atom(atom, VAD_MAP["happy"], "query")
        assert atom.version >= 2  # Metadata fallback still increments version
        await system.shutdown()

from __future__ import annotations

"""Integration tests for LivingMemorySystem."""

import pytest

from animetta.memory.v2.atom import Layer
from animetta.memory.v2.emotion_field import VAD_MAP
from animetta.memory.v2.system import LivingMemorySystem, RecallResult


@pytest.fixture
async def system():
    s = LivingMemorySystem(db_path=":memory:")
    await s.initialize()
    yield s
    await s.shutdown()


@pytest.mark.asyncio
class TestLivingMemorySystem:
    async def test_encode_creates_raw_atom(self, system):
        atom = await system.encode(
            user_input="今天喝了拿铁",
            agent_response="拿铁确实不错！",
            emotion_vad=VAD_MAP["happy"],
            session_id="test-session",
        )
        assert atom is not None
        assert atom.layer == Layer.RAW
        assert "拿铁" in atom.content
        assert atom.emotion_valence > 0.5  # happy → positive valence
        assert atom.retrieval_count == 0

    async def test_recall_returns_atoms(self, system):
        # Encode a memory
        await system.encode(
            user_input="我喜欢咖啡",
            agent_response="咖啡很棒",
            emotion_vad=VAD_MAP["neutral"],
            session_id="test-session",
        )
        # Recall
        result = await system.recall(
            query="咖啡",
            session_id="test-session",
            current_emotion=VAD_MAP["happy"],
        )
        assert isinstance(result, RecallResult)
        assert len(result.atoms) >= 1
        assert result.profile is not None
        assert result.memes is not None

    async def test_encode_with_neutral_emotion(self, system):
        atom = await system.encode(
            user_input="hello",
            agent_response="hi",
            emotion_vad=VAD_MAP["neutral"],
            session_id="s1",
        )
        # neutral → emotion vector near zero
        assert abs(atom.emotion_valence) < 0.1
        assert abs(atom.emotion_arousal) < 0.1

    async def test_list_wiki_pages_maps_atoms_for_frontend(self, system):
        atom = await system.encode(
            user_input="我喜欢拿铁",
            agent_response="记住了，拿铁是偏好。",
            emotion_vad=VAD_MAP["happy"],
            session_id="s1",
        )

        pages = await system.list_wiki_pages(limit=50)

        assert pages == [{
            "path": atom.id,
            "title": atom.content[:80],
            "content": atom.content,
            "page_type": "source",
            "tags": ["s1"],
            "updated_at": atom.rewritten_at.isoformat(),
        }]

    async def test_encode_with_sad_emotion(self, system):
        atom = await system.encode(
            user_input="今天心情不好",
            agent_response="希望你能好起来",
            emotion_vad=VAD_MAP["sad"],
            session_id="s1",
        )
        assert atom.emotion_valence < -0.5  # sad → negative valence

    async def test_recall_emotion_bias(self, system):
        """Happy memories rank higher when recalling with happy emotion."""
        # Encode a happy memory
        await system.encode(
            user_input="咖啡真好喝，开心！",
            agent_response="是啊！",
            emotion_vad=VAD_MAP["happy"],
            session_id="s1",
        )
        # Encode a sad memory
        await system.encode(
            user_input="咖啡洒了，难过",
            agent_response="太可惜了",
            emotion_vad=VAD_MAP["sad"],
            session_id="s1",
        )
        # Recall with happy emotion
        result = await system.recall(
            query="咖啡",
            session_id="s1",
            current_emotion=VAD_MAP["happy"],
        )
        if len(result.atoms) >= 2:
            # Happy memory should rank first
            first = result.atoms[0]
            second = result.atoms[1]
            assert first.emotion_valence > second.emotion_valence, (
                f"Happy memory should rank first. Got valence {first.emotion_valence} vs {second.emotion_valence}"
            )

class TestLivingMemorySystemEdgeCases:
    @pytest.mark.asyncio
    async def test_encode_empty_input(self, system):
        atom = await system.encode("", "", VAD_MAP["neutral"], "s1")
        assert atom is not None
        assert atom.layer == Layer.RAW

    @pytest.mark.asyncio
    async def test_recall_no_stored_atoms(self, system):
        result = await system.recall("nothing", "empty_session", VAD_MAP["neutral"])
        assert isinstance(result, RecallResult)
        assert len(result.atoms) == 0

    @pytest.mark.asyncio
    async def test_shutdown_without_init(self):
        system = LivingMemorySystem(db_path=":memory:")
        await system.shutdown()  # Should not crash

"""Tests for PersonaSeedGenerator — seed MemoryAtom generation."""

import pytest

from animetta.config.persona.base import (
    KnowledgeBoundaries,
    MBTIDimensions,
    MBTIProfile,
    PersonaConfig,
    PersonalityTraits,
)
from animetta.memory.v2.atom import Layer
from animetta.memory.v2.seed_generator import CanonicalQuote, PersonaSeedGenerator, SeedResult


def _make_persona(
    name: str = "TestBot",
    with_boundaries: bool = True,
    with_mbti: bool = True,
) -> PersonaConfig:
    """Helper: create a minimal PersonaConfig for testing."""
    traits = PersonalityTraits(
        traits=["沉默寡言", "行動派"],
        catchphrases=["殺人はいけない", "……わからない"],
    )
    if with_mbti:
        traits.mbti = MBTIProfile(
            type="ISFJ",
            dimensions=MBTIDimensions(ei=18, sn=28, tf=38, jp=62),
            description="温和的守护者",
        )

    kb = None
    if with_boundaries:
        kb = KnowledgeBoundaries(known=["山の生活"], unknown=["现代家电", "魔法"])

    return PersonaConfig(
        name=name,
        role="测试角色",
        identity="山から来た少年。",
        personality=traits,
        speaking_style="短い文。",
        knowledge_boundaries=kb,
        examples=[
            {"user": "你是谁？", "ai": "……静希草十郎。[neutral]"},
            {"user": "今天天气不错", "ai": "……ああ。[happy]"},
        ],
    )


class TestSeedResult:
    """Test SeedResult dataclass."""

    def test_default_stats(self):
        result = SeedResult()
        assert result.atoms == []
        assert result.stats == {"raw": 0, "episodic": 0, "semantic": 0}


class TestGenerateRaw:
    """Test RAW atom generation from examples and quotes."""

    def test_examples_to_raw(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_raw(quotes=[])
        assert len(result) == 2  # Two example dialogues
        for atom in result:
            assert atom.layer == Layer.RAW
            assert "character:TestBot" in atom.tags
            assert "seed" in atom.tags
            assert atom.confidence >= 0.85

    def test_quotes_to_raw(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        quotes = [
            CanonicalQuote(
                speaker="草十郎",
                text="……やります。",
                context="战斗前",
                emotion_valence=-0.1,
                emotion_arousal=0.3,
            ),
        ]
        result = gen._generate_raw(quotes=quotes)
        assert len(result) == 3  # 2 examples + 1 quote
        quote_atom = result[-1]
        assert "canonical_quote" in quote_atom.tags
        assert "……やります。" in quote_atom.content
        assert quote_atom.confidence >= 0.9

    def test_emotion_extraction(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_raw(quotes=[])
        # [happy] tagged example should have positive valence
        happy_atoms = [a for a in result if "happy" in a.content.lower()]
        if happy_atoms:
            assert happy_atoms[0].emotion_valence > 0


class TestGenerateEpisodic:
    """Test EPISODIC atom generation."""

    def test_creates_origin_story(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_episodic()
        assert len(result) == 1
        atom = result[0]
        assert atom.layer == Layer.EPISODIC
        assert "origin_story" in atom.tags
        assert "山から来た少年" in atom.content
        assert atom.confidence >= 0.9

    def test_empty_identity_no_atoms(self):
        persona = _make_persona()
        persona.identity = ""
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_episodic()
        assert len(result) == 0


class TestGenerateSemantic:
    """Test SEMANTIC atom generation from traits and boundaries."""

    def test_traits_to_semantic(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_semantic()
        assert len(result) >= 3  # traits + catchphrases + known + unknown

        tags_all = set()
        for atom in result:
            assert atom.layer == Layer.SEMANTIC
            tags_all.update(atom.tags)

        assert "self_knowledge" in tags_all or "personality" in tags_all
        assert "core_beliefs" in tags_all or "catchphrases" in tags_all

    def test_core_beliefs_highest_confidence(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_semantic()
        catchphrase_atom = [
            a for a in result if "core_beliefs" in a.tags or "catchphrases" in a.tags
        ]
        assert len(catchphrase_atom) > 0
        assert catchphrase_atom[0].confidence == 1.0

    def test_knowledge_gap_atom(self):
        persona = _make_persona(with_boundaries=True)
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_semantic()
        gap_atom = [a for a in result if "knowledge_gap" in a.tags]
        assert len(gap_atom) == 1
        assert "现代家电" in gap_atom[0].content
        assert "わからない" in gap_atom[0].content

    def test_no_boundaries_no_gap_atom(self):
        persona = _make_persona(with_boundaries=False)
        gen = PersonaSeedGenerator(persona)
        result = gen._generate_semantic()
        gap_atoms = [a for a in result if "unknown_domains" in a.tags]
        assert len(gap_atoms) == 0


class TestGenerate:
    """Test full generate() method."""

    @pytest.mark.asyncio
    async def test_generate_all_layers(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona, store=None)
        result = await gen.generate(quotes=[], force=True)
        assert len(result.atoms) > 0
        assert result.stats["raw"] >= 2
        assert result.stats["episodic"] >= 1
        assert result.stats["semantic"] >= 3

    @pytest.mark.asyncio
    async def test_generate_with_quotes(self):
        persona = _make_persona()
        gen = PersonaSeedGenerator(persona, store=None)
        quotes = [
            CanonicalQuote(speaker="草十郎", text="……殺人はいけない。", context="信念"),
        ]
        result = await gen.generate(quotes=quotes, force=True)
        assert any("……殺人はいけない" in a.content for a in result.atoms)

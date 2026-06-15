"""Tests for CharacterMemoryFilter — boundary filtering and MBTI ranking."""

from datetime import UTC, datetime

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.character_filter import CharacterMemoryFilter


def _make_atom(
    content: str,
    layer: Layer = Layer.RAW,
    valence: float = 0.0,
    arousal: float = 0.0,
    summary: str | None = None,
) -> MemoryAtom:
    """Helper: create a minimal MemoryAtom for testing."""
    return MemoryAtom(
        id=f"test-{content[:8]}",
        layer=layer,
        content=content,
        summary=summary,
        occurred_at=datetime.now(UTC),
        rewritten_at=datetime.now(UTC),
        version=1,
        confidence=0.5,
        salience=0.5,
        emotion_valence=valence,
        emotion_arousal=arousal,
        emotion_dominance=0.0,
        tags=[],
    )


class TestFilterByBoundaries:
    """Test knowledge boundary filtering."""

    def test_no_unknown_no_filtering(self):
        atoms = [_make_atom("微波炉的使用方法"), _make_atom("山里的生活")]
        result = CharacterMemoryFilter.filter_by_boundaries(
            atoms, known=[], unknown=[],
        )
        assert len(result) == 2

    def test_filters_unknown_domain(self):
        atoms = [
            _make_atom("微波炉怎么用 — 按开始键加热"),
            _make_atom("山里的生活很安静"),
        ]
        result = CharacterMemoryFilter.filter_by_boundaries(
            atoms, known=[], unknown=["微波炉", "现代家电"],
        )
        assert len(result) == 1
        assert "山里的生活" in result[0].content

    def test_case_insensitive_matching(self):
        atoms = [_make_atom("MICROWAVE instructions")]
        result = CharacterMemoryFilter.filter_by_boundaries(
            atoms, known=[], unknown=["microwave"],
        )
        assert len(result) == 0

    def test_checks_summary_field(self):
        atoms = [
            _make_atom("普通对话内容", summary="关于微波炉的讨论总结"),
        ]
        result = CharacterMemoryFilter.filter_by_boundaries(
            atoms, known=[], unknown=["微波炉"],
        )
        assert len(result) == 0

    def test_multiple_unknown_domains(self):
        atoms = [
            _make_atom("现代家电的微波炉使用说明"),  # matches "现代家电"
            _make_atom("魔法的基本理论介绍"),        # matches "魔法"
            _make_atom("今天的晚饭很好吃"),           # no match
        ]
        result = CharacterMemoryFilter.filter_by_boundaries(
            atoms, known=[], unknown=["现代家电", "魔法"],
        )
        assert len(result) == 1
        assert "晚饭" in result[0].content


class TestRankByPersona:
    """Test MBTI-based ranking."""

    def test_default_no_reorder(self):
        atoms = [
            _make_atom("a", arousal=0.5),
            _make_atom("b", arousal=0.1),
        ]
        result = CharacterMemoryFilter.rank_by_persona(atoms)
        # With default MBTI (all 50), no bias applied — order unchanged
        assert len(result) == 2

    def test_isfj_prefers_emotional_memories(self):
        """ISFJ (TF<45 = feeling) should rank high-arousal atoms higher."""
        emotional = _make_atom("emotional", arousal=0.8, valence=0.5)
        factual = _make_atom("factual", arousal=0.05, valence=0.0)
        atoms = [factual, emotional]

        result = CharacterMemoryFilter.rank_by_persona(
            atoms,
            mbti_ei=18, mbti_sn=28, mbti_tf=38, mbti_jp=62,  # ISFJ
        )
        # Emotional should be ranked first
        assert result[0].content == "emotional"

    def test_intj_prefers_calm_memories(self):
        """INTJ (TF>55 = thinking) should prefer calm/low-arousal."""
        emotional = _make_atom("emotional", arousal=0.8, valence=0.5)
        factual = _make_atom("factual", arousal=0.05, valence=0.0)
        atoms = [emotional, factual]

        result = CharacterMemoryFilter.rank_by_persona(
            atoms,
            mbti_ei=20, mbti_sn=65, mbti_tf=80, mbti_jp=73,  # INTJ
        )
        # Factual/calm should rank higher for thinking type
        assert result[0].content == "factual"

    def test_semantic_boost_for_judging(self):
        """Judging types (JP>55) prefer SEMANTIC (explicit beliefs)."""
        semantic = _make_atom("belief", layer=Layer.SEMANTIC, arousal=0.1)
        raw = _make_atom("raw experience", layer=Layer.RAW, arousal=0.1)
        atoms = [raw, semantic]

        result = CharacterMemoryFilter.rank_by_persona(
            atoms,
            mbti_jp=70,  # Judging
        )
        assert result[0].content == "belief"


class TestApply:
    """Test convenience apply() method."""

    def test_apply_both_filter_and_rank(self):
        atoms = [
            _make_atom("微波炉用法", arousal=0.5),
            _make_atom("快乐的山中回忆", arousal=0.8, valence=0.6),
            _make_atom("青子生气了", arousal=0.4, valence=-0.3),
        ]

        result = CharacterMemoryFilter.apply(
            atoms,
            known=[],
            unknown=["微波炉"],
            mbti_ei=18, mbti_sn=28, mbti_tf=38, mbti_jp=62,  # ISFJ
        )
        # "微波炉" should be filtered out
        assert len(result) == 2
        # ISFJ prefers emotional — "快乐的山中回忆" (high arousal+valence) should rank first
        assert result[0].content == "快乐的山中回忆"

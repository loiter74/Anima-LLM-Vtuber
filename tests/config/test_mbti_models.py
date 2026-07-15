from __future__ import annotations

from animetta.config.persona import PersonaConfig

"""Tests for MBTI Pydantic models (config/persona/base.py)"""

import sys
from pathlib import Path

import pytest

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from animetta.config.persona import (
    MBTIDimensionDelta,
    MBTIDimensions,
    MBTIProfile,
    PersonalityTraits,
)

# ═══════════════════════════════════════════════════════════════
# Test MBTIDimensions
# ═══════════════════════════════════════════════════════════════


class TestMBTIDimensions:
    """Tests for MBTIDimensions default values and methods"""

    def test_default_values_are_all_50(self):
        dims = MBTIDimensions()
        assert dims.ei == 50
        assert dims.sn == 50
        assert dims.tf == 50
        assert dims.jp == 50

    def test_values_are_clamped_to_0_100(self):
        """Pydantic ge=0, le=100 constraints clamp out-of-range values"""
        dims = MBTIDimensions(ei=-10, sn=150, tf=200, jp=-5)
        assert dims.ei == 0
        assert dims.sn == 100
        assert dims.tf == 100
        assert dims.jp == 0

    def test_boundary_values_accepted(self):
        """Values exactly at boundaries are accepted without clamping"""
        dims = MBTIDimensions(ei=0, sn=100, tf=0, jp=100)
        assert dims.ei == 0
        assert dims.sn == 100
        assert dims.tf == 0
        assert dims.jp == 100

    # ── to_mbti_type() ──────────────────────────────────────

    def test_to_mbti_type_returns_INTJ(self):
        """ei=20 (<50) → I, sn=65 (>50) → N, tf=80 (>50) → T, jp=73 (>50) → J"""
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        assert dims.to_mbti_type() == "INTJ"

    def test_to_mbti_type_returns_ESFP(self):
        """ei=80 (>50) → E, sn=30 (<50) → S, tf=20 (<50) → F, jp=30 (<50) → P"""
        dims = MBTIDimensions(ei=80, sn=30, tf=20, jp=30)
        assert dims.to_mbti_type() == "ESFP"

    def test_to_mbti_type_all_50_uses_second_letter(self):
        """At exactly 50, each dimension falls to the else branch (not >50) → ISFP"""
        dims = MBTIDimensions(ei=50, sn=50, tf=50, jp=50)
        assert dims.to_mbti_type() == "ISFP"

    def test_to_mbti_type_edge_cases(self):
        """Values exactly at thresholds (50/51) produce correct letters"""
        # ei=51 (>50) → E, else I
        dims = MBTIDimensions(ei=51, sn=51, tf=51, jp=51)
        assert dims.to_mbti_type() == "ENTJ"
        # ei=50 (not >50) → I, sn=51 (>50) → N, tf=50 (not >50) → F, jp=51 (>50) → J
        dims = MBTIDimensions(ei=50, sn=51, tf=50, jp=51)
        assert dims.to_mbti_type() == "INFJ"

    # ── describe_dimension() ─────────────────────────────────

    def test_describe_ei_at_extreme_introversion(self):
        """Value close to 0 → '极度内向'"""
        dims = MBTIDimensions(ei=10)
        assert dims.describe_dimension("ei") == "极度内向"

    def test_describe_ei_at_mild_introversion(self):
        """Value close to 25 → '内向倾向'"""
        dims = MBTIDimensions(ei=30)
        assert dims.describe_dimension("ei") == "内向倾向"

    def test_describe_ei_at_balance(self):
        """Value exactly 50 → '平衡'"""
        dims = MBTIDimensions(ei=50)
        assert dims.describe_dimension("ei") == "平衡"

    def test_describe_ei_at_mild_extraversion(self):
        """Value close to 75 → '外向倾向'"""
        dims = MBTIDimensions(ei=70)
        assert dims.describe_dimension("ei") == "外向倾向"

    def test_describe_ei_at_extreme_extraversion(self):
        """Value close to 100 → '极度外向'"""
        dims = MBTIDimensions(ei=90)
        assert dims.describe_dimension("ei") == "极度外向"

    def test_describe_sn_at_extreme_sensing(self):
        dims = MBTIDimensions(sn=10)
        assert dims.describe_dimension("sn") == "极度实感"

    def test_describe_sn_at_extreme_intuition(self):
        dims = MBTIDimensions(sn=90)
        assert dims.describe_dimension("sn") == "极度直觉"

    def test_describe_tf_at_mild_feeling(self):
        dims = MBTIDimensions(tf=30)
        assert dims.describe_dimension("tf") == "共情倾向"

    def test_describe_tf_at_mild_thinking(self):
        dims = MBTIDimensions(tf=70)
        assert dims.describe_dimension("tf") == "理性倾向"

    def test_describe_jp_at_extreme_perceiving(self):
        dims = MBTIDimensions(jp=10)
        assert dims.describe_dimension("jp") == "极度随性"

    def test_describe_jp_at_extreme_judging(self):
        dims = MBTIDimensions(jp=100)
        assert dims.describe_dimension("jp") == "极度计划"

    def test_describe_unknown_dimension_returns_balance(self):
        dims = MBTIDimensions()
        assert dims.describe_dimension("unknown") == "平衡"


# ═══════════════════════════════════════════════════════════════
# Test MBTIDimensionDelta
# ═══════════════════════════════════════════════════════════════


class TestMBTIDimensionDelta:
    """Tests for MBTIDimensionDelta"""

    def test_delta_is_required(self):
        with pytest.raises(ValueError, match="delta"):
            MBTIDimensionDelta()

    def test_confidence_defaults_to_0_5(self):
        d = MBTIDimensionDelta(delta=5)
        assert d.delta == 5
        assert d.confidence == 0.5

    def test_evidence_defaults_to_empty_string(self):
        d = MBTIDimensionDelta(delta=-2)
        assert d.evidence == ""

    def test_all_fields_set(self):
        d = MBTIDimensionDelta(delta=3, confidence=0.8, evidence="User prefers structure")
        assert d.delta == 3
        assert d.confidence == 0.8
        assert d.evidence == "User prefers structure"

    def test_confidence_is_clamped_to_0_1(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MBTIDimensionDelta(delta=1, confidence=2.0)
        with pytest.raises(ValidationError):
            MBTIDimensionDelta(delta=1, confidence=-0.5)

    def test_delta_accepts_negative_values(self):
        d = MBTIDimensionDelta(delta=-10)
        assert d.delta == -10


# ═══════════════════════════════════════════════════════════════
# Test MBTIProfile
# ═══════════════════════════════════════════════════════════════


class TestMBTIProfile:
    """Tests for MBTIProfile default values"""

    def test_type_defaults_to_INTP(self):
        profile = MBTIProfile()
        assert profile.type == "INTP"

    def test_dimensions_defaults_to_fresh_mbti_dimensions(self):
        profile = MBTIProfile()
        assert isinstance(profile.dimensions, MBTIDimensions)
        assert profile.dimensions.ei == 50
        assert profile.dimensions.sn == 50

    def test_description_defaults_to_empty(self):
        profile = MBTIProfile()
        assert profile.description == ""

    def test_confidence_defaults_to_0_5(self):
        profile = MBTIProfile()
        assert profile.confidence == 0.5

    def test_custom_values(self):
        dims = MBTIDimensions(ei=80, sn=30, tf=20, jp=30)
        profile = MBTIProfile(
            type="ESFP",
            dimensions=dims,
            description="Outgoing and observant",
            confidence=0.9,
        )
        assert profile.type == "ESFP"
        assert profile.dimensions.ei == 80
        assert profile.dimensions.sn == 30
        assert profile.description == "Outgoing and observant"
        assert profile.confidence == 0.9


# ═══════════════════════════════════════════════════════════════
# Test PersonalityTraits + MBTI integration
# ═══════════════════════════════════════════════════════════════


class TestPersonalityTraitsMBTI:
    """Tests for MBTI field in PersonalityTraits"""

    def test_default_personality_has_no_mbti(self):
        """Backward compatibility: mbti is None by default"""
        traits = PersonalityTraits()
        assert traits.mbti is None

    def test_can_set_mbti_profile_on_traits(self):
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims)
        traits = PersonalityTraits(mbti=mbti)
        assert traits.mbti is not None
        assert traits.mbti.type == "INTJ"
        assert traits.mbti.dimensions.ei == 20

    def test_persona_config_from_dict_with_mbti(self):
        """PersonaConfig parses correctly when mbti field is present"""
        data = {
            "name": "MBTIBot",
            "personality": {
                "mbti": {
                    "type": "ENFP",
                    "dimensions": {"ei": 80, "sn": 75, "tf": 30, "jp": 25},
                    "description": "The campaigner",
                    "confidence": 0.85,
                }
            },
        }
        config = PersonaConfig(**data)
        assert config.personality.mbti is not None
        assert config.personality.mbti.type == "ENFP"
        assert config.personality.mbti.dimensions.ei == 80
        assert config.personality.mbti.dimensions.sn == 75
        assert config.personality.mbti.description == "The campaigner"
        assert config.personality.mbti.confidence == 0.85

    def test_persona_config_without_mbti_still_works(self):
        """Backward compatibility: PersonaConfig without mbti field raises no error"""
        data = {
            "name": "SimpleBot",
            "personality": {"traits": ["friendly"]},
        }
        config = PersonaConfig(**data)
        assert config.personality.mbti is None
        assert config.personality.traits == ["friendly"]

    def test_persona_config_explicit_none_mbti(self):
        """Explicit mbti=None in dict works the same as omitted"""
        data = {
            "name": "NoMbtiBot",
            "personality": {"mbti": None},
        }
        config = PersonaConfig(**data)
        assert config.personality.mbti is None


# ═══════════════════════════════════════════════════════════════
# Test build_system_prompt with MBTI
# ═══════════════════════════════════════════════════════════════


class TestBuildSystemPromptMBTI:
    """Tests for build_system_prompt MBTI section"""

    def test_includes_mbti_section_when_configured(self):
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims, description="Analytical strategist")
        traits = PersonalityTraits(mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        assert "MBTI 人格类型" in prompt

    def test_includes_type_label_in_prompt(self):
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims)
        traits = PersonalityTraits(mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        assert "INTJ" in prompt

    def test_omits_mbti_section_when_not_configured(self):
        """Backward compatibility: no mbti → no MBTI section in prompt"""
        config = PersonaConfig()
        prompt = config.build_system_prompt()
        assert "MBTI 人格类型" not in prompt

    def test_includes_dimension_descriptions(self):
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims)
        traits = PersonalityTraits(mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        assert "内向" in prompt
        assert "直觉" in prompt
        assert "理性" in prompt
        assert "判断" in prompt

    def test_includes_dimension_percentages(self):
        """Each dimension shows its percentage values"""
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims)
        traits = PersonalityTraits(mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        # E/I: 内向(80%) ↔ 外向(20%)
        assert "20%" in prompt
        assert "80%" in prompt

    def test_includes_mbti_description_text(self):
        """When MBTIProfile has a description, it appears in the prompt"""
        dims = MBTIDimensions(ei=80, sn=30, tf=20, jp=30)
        mbti = MBTIProfile(type="ESFP", dimensions=dims, description="The entertainer")
        traits = PersonalityTraits(mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        assert "The entertainer" in prompt

    def test_mbti_section_placement_after_traits(self):
        """MBTI section appears after personality traits in the prompt"""
        dims = MBTIDimensions(ei=20, sn=65, tf=80, jp=73)
        mbti = MBTIProfile(type="INTJ", dimensions=dims)
        traits = PersonalityTraits(traits=["analytical"], mbti=mbti)
        config = PersonaConfig(personality=traits)
        prompt = config.build_system_prompt()
        assert prompt.index("性格特征") < prompt.index("MBTI 人格类型")

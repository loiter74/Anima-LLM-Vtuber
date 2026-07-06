"""Tests for KnowledgeBoundaries model and PersonaConfig integration."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from animetta.config.persona.base import (
    KnowledgeBoundaries,
    PersonaConfig,
)


class TestKnowledgeBoundaries:
    """Test KnowledgeBoundaries Pydantic model."""

    def test_default_values(self):
        kb = KnowledgeBoundaries()
        assert kb.known == []
        assert kb.unknown == []

    def test_with_domains(self):
        kb = KnowledgeBoundaries(known=["山の生活", "武道"], unknown=["现代家电", "魔法"])
        assert kb.known == ["山の生活", "武道"]
        assert kb.unknown == ["现代家电", "魔法"]

    def test_empty_lists_valid(self):
        kb = KnowledgeBoundaries(known=[], unknown=[])
        assert kb.known == []
        assert kb.unknown == []


class TestPersonaConfigBoundaries:
    """Test PersonaConfig knowledge_boundaries field and prompt injection."""

    def test_no_boundaries_by_default(self):
        cfg = PersonaConfig(name="Test")
        assert cfg.knowledge_boundaries is None

    def test_with_boundaries(self):
        kb = KnowledgeBoundaries(known=["a"], unknown=["b"])
        cfg = PersonaConfig(name="Test", knowledge_boundaries=kb)
        assert cfg.knowledge_boundaries is not None
        assert cfg.knowledge_boundaries.known == ["a"]
        assert cfg.knowledge_boundaries.unknown == ["b"]

    def test_system_prompt_includes_boundaries(self):
        kb = KnowledgeBoundaries(known=["山の生活"], unknown=["现代家电"])
        cfg = PersonaConfig(
            name="静希草十郎",
            identity="山から来た少年。",
            knowledge_boundaries=kb,
        )
        prompt = cfg.build_system_prompt()
        assert "知識边界" in prompt or "知识边界" in prompt
        assert "山の生活" in prompt
        assert "现代家电" in prompt
        assert "绝对不要编造答案" in prompt

    def test_system_prompt_without_boundaries(self):
        cfg = PersonaConfig(name="Test", identity="hello")
        prompt = cfg.build_system_prompt()
        assert "知識边界" not in prompt
        assert "知识边界" not in prompt
        assert "绝对不要编造答案" not in prompt

    def test_yaml_roundtrip(self):
        """Test loading from YAML with knowledge_boundaries."""
        yaml_content = """
name: "TestBot"
role: "tester"
identity: "I am a test."
speaking_style: "test"
knowledge_boundaries:
  known:
    - "area A"
    - "area B"
  unknown:
    - "area X"
    - "area Y"
"""
        with NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            f.flush()
            cfg = PersonaConfig.from_yaml(f.name)

        assert cfg.name == "TestBot"
        assert cfg.knowledge_boundaries is not None
        assert cfg.knowledge_boundaries.known == ["area A", "area B"]
        assert cfg.knowledge_boundaries.unknown == ["area X", "area Y"]

        Path(f.name).unlink(missing_ok=True)

    def test_yaml_without_boundaries(self):
        """Test loading from YAML without knowledge_boundaries."""
        yaml_content = """
name: "TestBot"
role: "tester"
identity: "I am a test."
speaking_style: "test"
"""
        with NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            cfg = PersonaConfig.from_yaml(f.name)

        assert cfg.knowledge_boundaries is None

        Path(f.name).unlink(missing_ok=True)

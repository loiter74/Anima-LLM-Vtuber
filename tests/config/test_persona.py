from __future__ import annotations

from animetta.config.persona import EnhancedPersonaBuilder, PersonaConfig
from animetta.config.persona.base import (
    BehaviorRules,
    PersonalityTraits,
    list_available_personas,
)

"""Tests for PersonaConfig (config/persona/base.py)"""

import sys
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# ═══════════════════════════════════════════════════════════════
# Sample YAML data for tests
# ═══════════════════════════════════════════════════════════════

SAMPLE_PERSONA_YAML = """
name: "TestBot"
role: "测试助手"
identity: "你是一个用于测试的助手。"
speaking_style: "简洁明了"
emoji_style: "每个回复使用1-2个表情"
common_emojis:
  - "😊"
  - "👍"
language_mix: true
slang_words:
  - "绝了"
  - "666"
personality:
  traits:
    - "友好"
    - "耐心"
  speaking_style:
    - "简洁"
    - "亲切"
  catchphrases:
    - "没问题！"
    - "交给我吧"
behavior:
  forbidden_phrases:
    - "我不知道"
  response_to_praise: "谢谢夸奖！"
  response_to_criticism: "谢谢反馈，我会改进的"
  special_behaviors:
    polite: true
examples:
  - user: "你好"
    ai: "你好！有什么我可以帮你的吗？"
"""

# Pre-parsed YAML data for tests (to avoid conflict with mocked yaml.safe_load)
_PARSED_PERSONA_DATA = {
    "name": "TestBot",
    "role": "测试助手",
    "identity": "你是一个用于测试的助手。",
    "speaking_style": "简洁明了",
    "emoji_style": "每个回复使用1-2个表情",
    "common_emojis": ["😊", "👍"],
    "language_mix": True,
    "slang_words": ["绝了", "666"],
    "personality": {
        "traits": ["友好", "耐心"],
        "speaking_style": ["简洁", "亲切"],
        "catchphrases": ["没问题！", "交给我吧"],
    },
    "behavior": {
        "forbidden_phrases": ["我不知道"],
        "response_to_praise": "谢谢夸奖！",
        "response_to_criticism": "谢谢反馈，我会改进的",
        "special_behaviors": {"polite": True},
    },
    "examples": [{"user": "你好", "ai": "你好！有什么我可以帮你的吗？"}],
}


# ═══════════════════════════════════════════════════════════════
# Test PersonalityTraits
# ═══════════════════════════════════════════════════════════════


class TestPersonalityTraitsDefaults:
    """Tests for PersonalityTraits default values"""

    def test_traits_defaults_to_empty_list(self):
        traits = PersonalityTraits()
        assert traits.traits == []

    def test_speaking_style_defaults_to_empty_list(self):
        traits = PersonalityTraits()
        assert traits.speaking_style == []

    def test_catchphrases_defaults_to_empty_list(self):
        traits = PersonalityTraits()
        assert traits.catchphrases == []

    def test_set_traits_values(self):
        traits = PersonalityTraits(
            traits=["friendly", "funny"],
            speaking_style=["casual"],
            catchphrases=["hello!"],
        )
        assert traits.traits == ["friendly", "funny"]
        assert traits.speaking_style == ["casual"]
        assert traits.catchphrases == ["hello!"]


# ═══════════════════════════════════════════════════════════════
# Test BehaviorRules
# ═══════════════════════════════════════════════════════════════


class TestBehaviorRulesDefaults:
    """Tests for BehaviorRules default values"""

    def test_forbidden_phrases_has_chinese_defaults(self):
        rules = BehaviorRules()
        assert "作为一个AI语言模型" in rules.forbidden_phrases
        assert "我无法" in rules.forbidden_phrases
        assert "我不确定" in rules.forbidden_phrases

    def test_response_templates_default_to_none(self):
        rules = BehaviorRules()
        assert rules.response_to_praise is None
        assert rules.response_to_criticism is None

    def test_special_behaviors_defaults_to_empty_dict(self):
        rules = BehaviorRules()
        assert rules.special_behaviors == {}

    def test_set_forbidden_phrases(self):
        rules = BehaviorRules(forbidden_phrases=["bad phrase"])
        assert rules.forbidden_phrases == ["bad phrase"]
        assert "作为一个AI语言模型" not in rules.forbidden_phrases


# ═══════════════════════════════════════════════════════════════
# Test PersonaConfig defaults
# ═══════════════════════════════════════════════════════════════


class TestPersonaConfigDefaults:
    """Tests for PersonaConfig default values"""

    def test_default_name_is_anima(self):
        config = PersonaConfig()
        assert config.name == "Anima"

    def test_default_role_is_ai_helper(self):
        config = PersonaConfig()
        assert config.role == "AI 助手"

    def test_default_identity(self):
        config = PersonaConfig()
        assert config.identity == "你是一个友好的 AI 助手。"

    def test_default_avatar_is_none(self):
        config = PersonaConfig()
        assert config.avatar is None

    def test_default_speaking_style_is_empty(self):
        config = PersonaConfig()
        assert config.speaking_style == ""

    def test_default_examples_is_empty(self):
        config = PersonaConfig()
        assert config.examples == []

    def test_default_emoji_style_is_empty(self):
        config = PersonaConfig()
        assert config.emoji_style == ""

    def test_default_common_emojis_is_empty(self):
        config = PersonaConfig()
        assert config.common_emojis == []

    def test_default_language_mix_is_false(self):
        config = PersonaConfig()
        assert config.language_mix is False

    def test_default_slang_words_is_empty(self):
        config = PersonaConfig()
        assert config.slang_words == []

    def test_default_live2d_prompt_is_none(self):
        config = PersonaConfig()
        assert config.live2d_prompt is None

    def test_default_personality_is_instance(self):
        config = PersonaConfig()
        assert isinstance(config.personality, PersonalityTraits)

    def test_default_behavior_is_instance(self):
        config = PersonaConfig()
        assert isinstance(config.behavior, BehaviorRules)


# ═══════════════════════════════════════════════════════════════
# Test build_system_prompt
# ═══════════════════════════════════════════════════════════════


class TestBuildSystemPrompt:
    """Tests for PersonaConfig.build_system_prompt"""

    def test_includes_mandatory_instructions(self):
        """build_system_prompt always includes the critical instructions section"""
        config = PersonaConfig()
        prompt = config.build_system_prompt()
        assert "重要指令" in prompt
        assert "CRITICAL INSTRUCTIONS" in prompt
        assert "直接对话" in prompt

    def test_includes_role_and_identity(self):
        """build_system_prompt includes role and identity"""
        config = PersonaConfig(name="Bot", role="AI Assistant", identity="You are a friendly bot.")
        prompt = config.build_system_prompt()
        assert "AI Assistant" in prompt
        assert "You are a friendly bot." in prompt

    def test_includes_personality_traits(self):
        """build_system_prompt lists personality traits"""
        config = PersonaConfig(
            personality=PersonalityTraits(traits=["friendly", "confident"]),
        )
        prompt = config.build_system_prompt()
        assert "friendly" in prompt
        assert "confident" in prompt

    def test_skips_personality_when_empty(self):
        """build_system_prompt skips personality section when no traits"""
        config = PersonaConfig()
        prompt = config.build_system_prompt()
        assert "性格特征" not in prompt
        assert "Personality Traits" not in prompt

    def test_includes_speaking_style(self):
        """build_system_prompt includes speaking style when set"""
        config = PersonaConfig(speaking_style="Be concise and witty.")
        prompt = config.build_system_prompt()
        assert "Be concise and witty." in prompt
        assert "Speaking Style" in prompt

    def test_skips_speaking_style_when_empty(self):
        """build_system_prompt skips speaking style section when empty"""
        config = PersonaConfig(speaking_style="")
        prompt = config.build_system_prompt()
        assert "Speaking Style" not in prompt

    def test_includes_forbidden_phrases(self):
        """build_system_prompt includes forbidden phrases"""
        config = PersonaConfig(
            behavior=BehaviorRules(forbidden_phrases=["bad word"]),
        )
        prompt = config.build_system_prompt()
        assert "禁止说" in prompt
        assert "bad word" in prompt

    def test_includes_praise_response(self):
        """build_system_prompt includes response template for praise"""
        config = PersonaConfig(
            behavior=BehaviorRules(response_to_praise="Thanks!"),
        )
        prompt = config.build_system_prompt()
        assert "面对夸奖" in prompt
        assert "Thanks!" in prompt

    def test_includes_criticism_response(self):
        """build_system_prompt includes response template for criticism"""
        config = PersonaConfig(
            behavior=BehaviorRules(response_to_criticism="I'll improve."),
        )
        prompt = config.build_system_prompt()
        assert "面对质疑" in prompt
        assert "I'll improve." in prompt

    def test_skips_behavior_when_empty(self):
        """build_system_prompt skips behavior section when no rules set"""
        config = PersonaConfig(
            behavior=BehaviorRules(forbidden_phrases=[], response_to_praise=None)
        )
        prompt = config.build_system_prompt()
        # The keyword "行为准则" appears in mandatory instructions; check section header instead
        assert "## 行为准则 (Behavior Rules)" not in prompt

    def test_includes_emoji_style(self):
        """build_system_prompt includes emoji style when set"""
        config = PersonaConfig(emoji_style="Use emojis often")
        prompt = config.build_system_prompt()
        assert "Use emojis often" in prompt
        assert "Emoji" in prompt

    def test_includes_common_emojis(self):
        """build_system_prompt lists common emojis"""
        config = PersonaConfig(common_emojis=["😊", "👍"])
        prompt = config.build_system_prompt()
        assert "😊" in prompt
        assert "👍" in prompt

    def test_skips_emoji_when_not_set(self):
        """build_system_prompt skips emoji section when not configured"""
        config = PersonaConfig()
        prompt = config.build_system_prompt()
        assert "Emoji" not in prompt or ("Emoji" in prompt and "常用" not in prompt)

    def test_includes_slang_words(self):
        """build_system_prompt includes internet slang words"""
        config = PersonaConfig(slang_words=["yyds", "绝绝子"])
        prompt = config.build_system_prompt()
        assert "yyds" in prompt
        assert "绝绝子" in prompt

    def test_includes_live2d_prompt_parameter(self):
        """build_system_prompt includes live2d_prompt when passed as parameter"""
        config = PersonaConfig()
        prompt = config.build_system_prompt(live2d_prompt="Use Live2D expressions.")
        assert "Use Live2D expressions." in prompt

    def test_includes_live2d_prompt_from_config(self):
        """build_system_prompt includes live2d_prompt from config when set"""
        config = PersonaConfig(live2d_prompt="Config live2d prompt.")
        prompt = config.build_system_prompt()
        assert "Config live2d prompt." in prompt

    def test_live2d_parameter_overrides_config(self):
        """build_system_prompt live2d_prompt parameter overrides config value"""
        config = PersonaConfig(live2d_prompt="Config value")
        prompt = config.build_system_prompt(live2d_prompt="Override value")
        assert "Override value" in prompt
        assert "Config value" not in prompt

    def test_includes_example_conversations(self):
        """build_system_prompt includes example conversations"""
        config = PersonaConfig(
            examples=[{"user": "Hello", "ai": "Hi there!"}],
        )
        prompt = config.build_system_prompt()
        assert "Hello" in prompt
        assert "Hi there!" in prompt

    def test_limits_examples_to_five(self):
        """build_system_prompt limits examples to 5"""
        examples = [{"user": f"Q{i}", "ai": f"A{i}"} for i in range(10)]
        config = PersonaConfig(examples=examples)
        prompt = config.build_system_prompt()
        # First 5 should be in output
        assert "Q0" in prompt
        assert "Q4" in prompt
        # 6th should NOT be in output
        assert "Q5" not in prompt

    def test_skips_examples_when_empty(self):
        """build_system_prompt skips examples section when no examples"""
        config = PersonaConfig()
        prompt = config.build_system_prompt()
        # The keyword "对话示例" appears in mandatory instructions; check section header instead
        assert "## 对话示例 (Examples)" not in prompt


# ═══════════════════════════════════════════════════════════════
# Test from_yaml
# ═══════════════════════════════════════════════════════════════


class TestFromYaml:
    """Tests for PersonaConfig.from_yaml"""

    @patch("yaml.safe_load")
    @patch("builtins.open", new_callable=mock_open, read_data="dummy")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_from_yaml_file(self, mock_exists, mock_file, mock_yaml_load):
        """from_yaml loads and parses YAML data into PersonaConfig"""
        mock_yaml_load.return_value = {
            "name": "TestBot",
            "role": "Tester",
            "identity": "Test identity.",
            "personality": {"traits": ["funny"]},
            "behavior": {"forbidden_phrases": ["no"]},
        }

        config = PersonaConfig.from_yaml("/fake/path.yaml")

        assert config.name == "TestBot"
        assert config.role == "Tester"
        assert config.identity == "Test identity."
        assert config.personality.traits == ["funny"]
        assert config.behavior.forbidden_phrases == ["no"]

    @patch("pathlib.Path.exists", return_value=False)
    def test_raises_file_not_found(self, mock_exists):
        """from_yaml raises FileNotFoundError when path doesn't exist"""
        with pytest.raises(FileNotFoundError):
            PersonaConfig.from_yaml("/nonexistent/path.yaml")

    @patch("yaml.safe_load")
    @patch("builtins.open", new_callable=mock_open, read_data="dummy")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_with_all_nested_models(self, mock_exists, mock_file, mock_yaml_load):
        """from_yaml properly constructs all nested Pydantic models"""
        mock_yaml_load.return_value = _PARSED_PERSONA_DATA

        config = PersonaConfig.from_yaml("/fake/persona.yaml")

        assert config.name == "TestBot"
        assert config.role == "测试助手"
        assert config.identity == "你是一个用于测试的助手。"
        assert isinstance(config.personality, PersonalityTraits)
        assert config.personality.traits == ["友好", "耐心"]
        assert config.personality.catchphrases == ["没问题！", "交给我吧"]
        assert isinstance(config.behavior, BehaviorRules)
        assert config.behavior.forbidden_phrases == ["我不知道"]
        assert config.behavior.response_to_praise == "谢谢夸奖！"
        assert config.behavior.special_behaviors == {"polite": True}
        assert config.language_mix is True
        assert config.slang_words == ["绝了", "666"]
        assert config.emoji_style == "每个回复使用1-2个表情"
        assert len(config.examples) == 1
        assert config.examples[0]["user"] == "你好"


# ═══════════════════════════════════════════════════════════════
# Test load classmethod
# ═══════════════════════════════════════════════════════════════


class TestLoad:
    """Tests for PersonaConfig.load"""

    @patch("animetta.config.persona.base.PersonaConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_load_by_name(self, mock_exists, mock_from_yaml):
        """load(name) reads YAML and calls from_yaml with correct path"""
        mock_from_yaml.return_value = PersonaConfig(name="TestBot")
        config = PersonaConfig.load(name="test_bot", personas_dir="/fake/personas")

        mock_from_yaml.assert_called_once()
        call_path = mock_from_yaml.call_args[0][0]
        assert "test_bot.yaml" in call_path or call_path.endswith("test_bot.yaml")
        assert config.name == "TestBot"

    @patch("pathlib.Path.exists", return_value=False)
    def test_load_returns_default_when_not_found_and_not_default(self, mock_exists):
        """load returns PersonaConfig() when name != 'default' and file not found"""
        config = PersonaConfig.load(name="nonexistent")
        assert isinstance(config, PersonaConfig)
        assert config.name == "Anima"

    @patch("pathlib.Path.exists", return_value=False)
    def test_load_raises_when_default_not_found(self, mock_exists):
        """load raises FileNotFoundError when 'default' persona is missing"""
        with pytest.raises(FileNotFoundError, match="Persona configuration not found"):
            PersonaConfig.load(name="default")

    @patch("animetta.config.persona.base.PersonaConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_load_with_custom_dir(self, mock_exists, mock_from_yaml):
        """load uses custom personas_dir when provided"""
        mock_from_yaml.return_value = PersonaConfig()
        PersonaConfig.load(name="custom", personas_dir="/custom/personas")

        mock_from_yaml.assert_called_once()
        call_path = mock_from_yaml.call_args[0][0]
        assert "/custom/personas" in call_path or "custom\\personas" in call_path

    @patch("animetta.config.persona.base.PersonaConfig.from_yaml")
    @patch("pathlib.Path.exists", return_value=True)
    def test_load_default_path_when_no_dir_provided(self, mock_exists, mock_from_yaml):
        """load uses project-relative default path when personas_dir is None"""
        mock_from_yaml.return_value = PersonaConfig()
        PersonaConfig.load(name="default")

        mock_from_yaml.assert_called_once()
        call_path = mock_from_yaml.call_args[0][0]
        assert "config" in call_path
        assert "personas" in call_path


class TestPersonaCatalog:
    """Tests for shared persona catalog helpers."""

    def test_list_available_personas_returns_sorted_yaml_stems(self, tmp_path):
        """list_available_personas returns sorted persona names from YAML files."""

        (tmp_path / "zeta.yaml").write_text("name: Zeta", encoding="utf-8")
        (tmp_path / "alpha.yaml").write_text("name: Alpha", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")

        assert list_available_personas(tmp_path) == ["alpha", "zeta"]

    def test_list_available_personas_falls_back_to_default_for_missing_dir(self, tmp_path):
        """list_available_personas falls back to default when directory is absent."""

        assert list_available_personas(tmp_path / "missing") == ["default"]


class TestEnhancedPersonaBuilder:
    """Tests for EnhancedPersonaBuilder persona loading."""

    def test_from_yaml_uses_project_personas_dir_by_default(self):
        """from_yaml(name) should load personas from the project config directory."""

        builder = EnhancedPersonaBuilder.from_yaml("default")

        assert builder.persona_path.name == "default.yaml"
        assert builder.persona_path.parent.name == "personas"
        assert builder.persona_path.parent.parent.name == "config"
        assert builder.persona_data["name"]


class TestAnimaV01Persona:
    """Regression tests for the Anima v0.1 roleplay persona."""

    def test_anima_v01_loads_short_roleplay_prompt(self):
        config = PersonaConfig.load(name="anima.v0.1")
        prompt = config.build_system_prompt()

        assert config.name == "Anima"
        assert config.role == "深夜赛博酒馆 AI VTuber"
        assert "被召唤者 X 从赛博世界强行召唤出来打工" in config.identity
        assert "直播观众统一称作“家人们”" in config.identity
        assert "直播观众统一称作“家人们”" in prompt
        assert "旅人们" not in prompt
        assert "先下结论，再套世界观，最后轻轻接住人" in prompt
        assert "虫子" in prompt
        assert "作为 AI" in config.behavior.forbidden_phrases
        assert "我理解你的意思" in config.behavior.forbidden_phrases
        assert "今天直播累不累？" in prompt
        assert "帮我写个代码" in prompt
        assert "需求文档呢？没有文档就想要输出" in prompt

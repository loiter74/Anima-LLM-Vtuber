from __future__ import annotations

from animetta.avatar.prompts import EmotionPromptBuilder, load_prompt_template

"""
Tests for EmotionPromptBuilder — emotion tag usage guide generation.
"""

import os
import tempfile

import pytest

# ============================================================
# EmotionPromptBuilder
# ============================================================

class TestEmotionPromptBuilderInit:
    """Initialization."""

    def test_default_init(self):
        """Default init uses DEFAULT_EMOTIONS and zh language."""
        builder = EmotionPromptBuilder()
        assert builder.language == "zh"
        assert "happy" in builder.emotions
        assert "neutral" in builder.emotions
        assert len(builder.emotions) == 6

    def test_custom_emotions(self):
        """Custom emotions dict overrides defaults."""
        emotions = {"ecstatic": "非常开心"}
        builder = EmotionPromptBuilder(emotions=emotions)
        assert builder.emotions == emotions
        assert "happy" not in builder.emotions

    def test_english_language(self):
        """English language setting."""
        builder = EmotionPromptBuilder(language="en")
        assert builder.language == "en"


class TestEmotionPromptBuilderBuildPrompt:
    """build_prompt() output."""

    def test_zh_prompt_contains_header(self):
        """Chinese prompt should contain correct header."""
        builder = EmotionPromptBuilder(language="zh")
        prompt = builder.build_prompt()
        assert "# Live2D 表情使用指南" in prompt
        assert "可用表情" in prompt
        assert "使用方法" in prompt
        assert "示例" in prompt
        assert "强制要求" in prompt

    def test_zh_prompt_contains_emotions(self):
        """Chinese prompt should list all emotions."""
        builder = EmotionPromptBuilder(language="zh")
        prompt = builder.build_prompt()
        assert "[happy]" in prompt
        assert "[sad]" in prompt
        assert "[angry]" in prompt
        assert "[neutral]" in prompt
        assert "[thinking]" in prompt

    def test_zh_prompt_contains_examples(self):
        """Chinese prompt should contain example sentences."""
        builder = EmotionPromptBuilder(language="zh")
        prompt = builder.build_prompt()
        assert "很高兴见到你" in prompt
        assert "让我想想" in prompt
        assert "这太不公平了" in prompt

    def test_en_prompt_contains_header(self):
        """English prompt should contain correct header."""
        builder = EmotionPromptBuilder(language="en")
        prompt = builder.build_prompt()
        assert "# Live2D Expression Guide" in prompt
        assert "Available Expressions" in prompt
        assert "Usage" in prompt
        assert "Examples" in prompt
        assert "Notes" in prompt

    def test_en_prompt_contains_examples(self):
        """English prompt should contain English examples."""
        builder = EmotionPromptBuilder(language="en")
        prompt = builder.build_prompt()
        assert "Nice to meet you" in prompt
        assert "Let me think" in prompt
        assert "This is unfair" in prompt

    def test_custom_emotions_in_prompt(self):
        """Custom emotions should appear in prompt output."""
        emotions = {"ecstatic": "extremely happy", "tired": "very tired"}
        builder = EmotionPromptBuilder(emotions=emotions, language="en")
        prompt = builder.build_prompt()
        assert "[ecstatic]" in prompt
        assert "[tired]" in prompt
        assert "[happy]" not in prompt  # not in custom emotions

    def test_zh_prompt_contains_usage_tips(self):
        """Chinese prompt should contain usage tips."""
        builder = EmotionPromptBuilder(language="zh")
        prompt = builder.build_prompt()
        assert "1. 根据语境选择合适的表情" in prompt
        assert "2. 一个回复中可以使用多个表情标签" in prompt
        assert "3. 表情标签放在对应情感词语之后效果更好" in prompt

    def test_en_prompt_contains_notes(self):
        """English prompt should contain numbered notes."""
        builder = EmotionPromptBuilder(language="en")
        prompt = builder.build_prompt()
        assert "1." in prompt
        assert "Don't overuse" in prompt or "don't overuse" in prompt


class TestEmotionPromptBuilderExamples:
    """Example generation."""

    def test_zh_examples_with_happy(self):
        """Chinese examples should include happy example."""
        builder = EmotionPromptBuilder(language="zh")
        examples = builder._get_examples()
        assert any("高兴" in ex for ex in examples)

    def test_zh_examples_with_sad(self):
        """Chinese examples should include sad example."""
        builder = EmotionPromptBuilder(language="zh")
        examples = builder._get_examples()
        assert any("难过" in ex for ex in examples)

    def test_en_examples_with_happy(self):
        """English examples should include happy example."""
        builder = EmotionPromptBuilder(language="en")
        examples = builder._get_examples_en()
        assert any("Nice to meet" in ex for ex in examples)

    def test_en_examples_with_angry(self):
        """English examples should include angry example."""
        builder = EmotionPromptBuilder(language="en")
        examples = builder._get_examples_en()
        assert any("unfair" in ex for ex in examples)

    def test_examples_respect_available_emotions(self):
        """Examples should only be generated for available emotions."""
        emotions = {"happy": "开心"}
        builder = EmotionPromptBuilder(emotions=emotions, language="zh")
        examples = builder._get_examples()
        assert len(examples) == 1  # Only happy example
        assert "很高兴见到你" in examples[0]

    def test_examples_respect_available_emotions_en(self):
        """English examples should respect available emotions."""
        emotions = {"surprised": "surprised"}
        builder = EmotionPromptBuilder(emotions=emotions, language="en")
        examples = builder._get_examples_en()
        assert len(examples) == 1
        assert "Wow" in examples[0]


class TestEmotionPromptBuilderFromConfig:
    """from_config classmethod."""

    def test_from_config_with_valid_emotions(self):
        """from_config should create builder from valid_emotions list."""
        config = {"valid_emotions": ["happy", "sad", "thinking"]}
        builder = EmotionPromptBuilder.from_config(config)
        assert "happy" in builder.emotions
        assert "sad" in builder.emotions
        assert "thinking" in builder.emotions
        assert "angry" not in builder.emotions

    def test_from_config_uses_default_descriptions(self):
        """from_config should use default descriptions for known emotions."""
        config = {"valid_emotions": ["happy"]}
        builder = EmotionPromptBuilder.from_config(config)
        assert builder.emotions["happy"] == "开心、快乐、愉快"

    def test_from_config_fallback_description(self):
        """Unknown emotions should use name as description."""
        config = {"valid_emotions": ["custom_emotion"]}
        builder = EmotionPromptBuilder.from_config(config)
        assert builder.emotions["custom_emotion"] == "custom_emotion"

    def test_from_config_empty_list(self):
        """Empty valid_emotions should fall back to default emotions ({} is falsy)."""
        config = {"valid_emotions": []}
        builder = EmotionPromptBuilder.from_config(config)
        # Empty emotions dict is falsy, so __init__ falls back to DEFAULT_EMOTIONS
        assert len(builder.emotions) == 6
        assert "happy" in builder.emotions


class TestLoadPromptTemplate:
    """load_prompt_template function."""

    def test_load_existing_template(self):
        """load_prompt_template should read existing file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("test template content")
            tmpl_path = f.name
        try:
            content = load_prompt_template(tmpl_path)
            assert content == "test template content"
        finally:
            os.unlink(tmpl_path)

    def test_load_nonexistent_template_raises(self):
        """load_prompt_template for non-existent file should raise."""
        with pytest.raises(FileNotFoundError, match="Prompt template not found"):
            load_prompt_template("/nonexistent/template.txt")

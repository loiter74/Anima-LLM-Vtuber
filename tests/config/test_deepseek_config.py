"""Tests for DeepSeek config, thinking mode, and extra_body passthrough."""

from __future__ import annotations

import pytest

from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig


# ── Config validation ────────────────────────────────────────


def test_thinking_disabled_by_default():
    cfg = DeepSeekLLMConfig(api_key="test")
    assert cfg.thinking == "disabled"


def test_thinking_enabled():
    cfg = DeepSeekLLMConfig(api_key="test", thinking="enabled")
    assert cfg.thinking == "enabled"


def test_thinking_disabled_explicit():
    cfg = DeepSeekLLMConfig(api_key="test", thinking="disabled")
    assert cfg.thinking == "disabled"


def test_thinking_invalid_rejected():
    """Invalid thinking modes must be rejected by Pydantic validation."""
    with pytest.raises(Exception):  # ValidationError
        DeepSeekLLMConfig(api_key="test", thinking="banana")


# ── extra_body passthrough ───────────────────────────────────


def test_from_config_disabled_produces_extra_body():
    from animetta.services.llm.openai_llm import OpenAILLM

    cfg = DeepSeekLLMConfig(api_key="test", thinking="disabled")
    llm = OpenAILLM.from_config(cfg)
    assert llm.extra_body == {"thinking": {"type": "disabled"}}


def test_from_config_enabled_produces_extra_body():
    from animetta.services.llm.openai_llm import OpenAILLM

    cfg = DeepSeekLLMConfig(api_key="test", thinking="enabled")
    llm = OpenAILLM.from_config(cfg)
    assert llm.extra_body == {"thinking": {"type": "enabled"}}


def test_openai_config_no_extra_body():
    """Standard OpenAI config should not produce extra_body."""
    from animetta.config.providers.llm.openai import OpenAILLMConfig
    from animetta.services.llm.openai_llm import OpenAILLM

    cfg = OpenAILLMConfig(api_key="test")
    llm = OpenAILLM.from_config(cfg)
    assert llm.extra_body == {}

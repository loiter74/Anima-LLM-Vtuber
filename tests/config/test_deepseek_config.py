"""Tests for DeepSeek config, thinking mode, and extra_body passthrough."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig
from animetta.config.providers.llm.openai import OpenAILLMConfig
from animetta.services.llm.openai_llm import OpenAILLM

# ── Config validation ────────────────────────────────────────


def test_thinking_disabled_by_default():
    cfg = DeepSeekLLMConfig(api_key="test")
    assert cfg.thinking == "disabled"


def test_realtime_roleplay_sampling_defaults_are_lively():
    """DeepSeek realtime roleplay should default to non-deterministic chat sampling."""
    cfg = DeepSeekLLMConfig(api_key="test")
    assert cfg.temperature >= 0.85
    assert cfg.top_p >= 0.9


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


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (
            DeepSeekLLMConfig(api_key="test", thinking="disabled"),
            {"thinking": {"type": "disabled"}},
        ),
        (
            DeepSeekLLMConfig(api_key="test", thinking="enabled"),
            {"thinking": {"type": "enabled"}},
        ),
        (OpenAILLMConfig(api_key="test"), {}),
    ],
    ids=["deepseek-disabled", "deepseek-enabled", "openai"],
)
def test_from_config_produces_provider_extra_body(config, expected):
    with (
        patch("httpx.AsyncClient"),
        patch("animetta.services.llm.openai_llm.AsyncOpenAI"),
    ):
        llm = OpenAILLM.from_config(config)

    assert llm.extra_body == expected

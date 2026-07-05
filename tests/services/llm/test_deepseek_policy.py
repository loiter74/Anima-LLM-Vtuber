"""Tests for DeepSeek runtime model policy."""

from animetta.services.llm.deepseek_policy import (
    resolve_policy,
)


def test_default_is_roleplay_flash():
    p = resolve_policy()
    assert p.model == "deepseek-v4-flash"
    assert p.thinking == "disabled"
    assert p.mode == "roleplay_realtime"


def test_bilibili_is_roleplay():
    p = resolve_policy(channel_id="bilibili_danmaku")
    assert p.model == "deepseek-v4-flash"
    assert p.thinking == "disabled"


def test_explicit_complex_is_pro_thinking():
    p = resolve_policy(explicit_complex=True)
    assert p.model == "deepseek-v4-pro"
    assert p.thinking == "enabled"
    assert p.mode == "complex_reasoning"


def test_explicit_complex_overrides_bilibili():
    p = resolve_policy(channel_id="bilibili", explicit_complex=True)
    assert p.mode == "complex_reasoning"

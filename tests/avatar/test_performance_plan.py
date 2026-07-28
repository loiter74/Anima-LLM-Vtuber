from typing import get_args

from animetta.avatar.performance import (
    CALM_PERFORMANCE_PLAN,
    Live2DPerformancePlan,
    PerformanceAccent,
    PerformanceBase,
    parse_performance_plan,
    validated_performance_payload,
)


def test_public_performance_types_only_expose_canonical_values() -> None:
    assert get_args(PerformanceBase) == ("calm", "annoyed", "surprised")
    assert get_args(PerformanceAccent) == ("none",)


def test_valid_marker_builds_llm_plan_and_strips_marker() -> None:
    result = parse_performance_plan("[live2d:surprised|medium|none] 晚上好，欢迎来到直播间。")

    assert result.plan == Live2DPerformancePlan(
        version=1,
        base="surprised",
        intensity="medium",
        accent="none",
        source="llm",
    )
    assert result.cleaned_text == "晚上好，欢迎来到直播间。"
    assert result.compatible_emotion == "surprised"
    assert result.fallback_reason is None


def test_first_valid_marker_wins_and_all_marker_shapes_are_stripped() -> None:
    result = parse_performance_plan(
        "[live2d:thinking|subtle|skeptical] 让我想想。"
        "[live2d:surprised|medium|startle]"
        "[live2d:not-real|extreme|dance]"
    )

    assert result.plan.base == "calm"
    assert result.plan.accent == "none"
    assert result.plan.source == "legacy"
    assert result.cleaned_text == "让我想想。"


def test_invalid_marker_falls_back_to_calm_without_leaking_marker() -> None:
    result = parse_performance_plan("[live2d:happy|strong|dance] 这句要正常朗读。")

    assert result.plan == CALM_PERFORMANCE_PLAN
    assert result.cleaned_text == "这句要正常朗读。"
    assert result.compatible_emotion == "neutral"
    assert result.fallback_reason == "invalid_marker"


def test_missing_marker_falls_back_to_calm() -> None:
    result = parse_performance_plan("普通回复。")

    assert result.plan == CALM_PERFORMANCE_PLAN
    assert result.cleaned_text == "普通回复。"
    assert result.fallback_reason == "missing_marker"


def test_validated_payload_rejects_unbounded_or_invalid_fields() -> None:
    valid = {
        "version": 1,
        "base": "thinking",
        "intensity": "subtle",
        "accent": "skeptical",
        "source": "llm",
    }

    assert validated_performance_payload(valid) == {
        "version": 1,
        "base": "calm",
        "intensity": "subtle",
        "accent": "none",
        "source": "legacy",
    }
    assert validated_performance_payload({**valid, "index": 4}) is None
    assert validated_performance_payload({**valid, "base": "furious"}) is None
    assert validated_performance_payload("thinking") is None


def test_legacy_happy_marker_maps_to_calm_plan() -> None:
    result = parse_performance_plan("你好！[happy] 很高兴见到你。")

    assert result.plan == Live2DPerformancePlan(
        version=1,
        base="calm",
        intensity="subtle",
        accent="none",
        source="legacy",
    )
    assert result.cleaned_text == "你好！ 很高兴见到你。"
    assert result.compatible_emotion == "happy"
    assert result.fallback_reason is None


def test_valid_new_marker_has_priority_over_legacy_marker() -> None:
    result = parse_performance_plan("[live2d:smug|subtle|sigh] 本小姐早就知道了。[angry]")

    assert result.plan.base == "calm"
    assert result.plan.accent == "none"
    assert result.plan.source == "legacy"
    assert result.compatible_emotion == "neutral"
    assert result.cleaned_text == "本小姐早就知道了。"


def test_deprecated_thinking_marker_maps_to_calm_without_leaking_marker() -> None:
    result = parse_performance_plan("[live2d:thinking|medium|skeptical] 让我想想。")

    assert result.plan == Live2DPerformancePlan(
        version=1,
        base="calm",
        intensity="medium",
        accent="none",
        source="legacy",
    )
    assert result.cleaned_text == "让我想想。"

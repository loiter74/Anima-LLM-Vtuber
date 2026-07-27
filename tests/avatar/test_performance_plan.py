from animetta.avatar.performance import (
    CALM_PERFORMANCE_PLAN,
    Live2DPerformancePlan,
    parse_performance_plan,
    validated_performance_payload,
)


def test_valid_marker_builds_llm_plan_and_strips_marker() -> None:
    result = parse_performance_plan("[live2d:cheerful|medium|brighten] 晚上好，欢迎来到直播间。")

    assert result.plan == Live2DPerformancePlan(
        version=1,
        base="cheerful",
        intensity="medium",
        accent="brighten",
        source="llm",
    )
    assert result.cleaned_text == "晚上好，欢迎来到直播间。"
    assert result.compatible_emotion == "happy"
    assert result.fallback_reason is None


def test_first_valid_marker_wins_and_all_marker_shapes_are_stripped() -> None:
    result = parse_performance_plan(
        "[live2d:thinking|subtle|skeptical] 让我想想。"
        "[live2d:surprised|medium|startle]"
        "[live2d:not-real|extreme|dance]"
    )

    assert result.plan.base == "thinking"
    assert result.plan.accent == "skeptical"
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

    assert validated_performance_payload(valid) == valid
    assert validated_performance_payload({**valid, "index": 4}) is None
    assert validated_performance_payload({**valid, "base": "furious"}) is None
    assert validated_performance_payload("thinking") is None


def test_legacy_happy_marker_maps_to_cheerful_plan() -> None:
    result = parse_performance_plan("你好！[happy] 很高兴见到你。")

    assert result.plan == Live2DPerformancePlan(
        version=1,
        base="cheerful",
        intensity="subtle",
        accent="none",
        source="legacy",
    )
    assert result.cleaned_text == "你好！ 很高兴见到你。"
    assert result.compatible_emotion == "happy"
    assert result.fallback_reason is None


def test_valid_new_marker_has_priority_over_legacy_marker() -> None:
    result = parse_performance_plan("[live2d:smug|subtle|sigh] 本小姐早就知道了。[angry]")

    assert result.plan.base == "smug"
    assert result.plan.source == "llm"
    assert result.compatible_emotion == "neutral"
    assert result.cleaned_text == "本小姐早就知道了。"

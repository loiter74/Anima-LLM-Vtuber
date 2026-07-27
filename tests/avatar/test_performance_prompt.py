from animetta.avatar.prompts import PerformancePromptBuilder
from animetta.config.runtime_reload import build_live2d_prompt


def test_performance_prompt_requires_one_leading_bounded_marker() -> None:
    prompt = PerformancePromptBuilder(language="zh").build_prompt()

    assert "[live2d:<base>|<intensity>|<accent>]" in prompt
    assert "回复最开头" in prompt
    assert "且只能输出一个" in prompt
    assert "calm | cheerful | concerned | annoyed | surprised | thinking | smug" in prompt
    assert "subtle | medium" in prompt
    assert "none | brighten | skeptical | startle | sigh" in prompt


def test_performance_prompt_is_calm_first_and_forbids_raw_controls() -> None:
    prompt = PerformancePromptBuilder(language="zh").build_prompt()

    assert "大多数回复使用 calm" in prompt
    assert "[live2d:calm|subtle|none]" in prompt
    assert "动作编号" in prompt
    assert "模型参数" in prompt


def test_performance_prompt_has_equivalent_english_contract() -> None:
    prompt = PerformancePromptBuilder(language="en").build_prompt()

    assert "exactly one marker" in prompt
    assert "[live2d:calm|subtle|none]" in prompt
    assert "raw parameter" in prompt


def test_runtime_live2d_prompt_uses_performance_builder(monkeypatch) -> None:
    class Live2DConfig:
        enabled = True

    monkeypatch.setattr(
        "animetta.config.live2d.get_live2d_config",
        lambda: Live2DConfig(),
    )
    monkeypatch.setattr(
        PerformancePromptBuilder,
        "build_prompt",
        lambda self: "SEMANTIC-PERFORMANCE-PROMPT",
    )

    prompt, warnings = build_live2d_prompt()

    assert prompt == "SEMANTIC-PERFORMANCE-PROMPT"
    assert warnings == []

"""Tests for prompt pipeline: full compile scenarios."""

from __future__ import annotations

import time

import pytest

from animetta.orchestration.prompting.pipeline import compile as compile_prompt


@pytest.mark.asyncio
async def test_persona_only():
    """Persona + default affinity section (no overlay, no memory).

    AffinityPromptSource always emits a section (default value 50), so the
    minimal prompt is persona + affinity + improvised chat = 3 sections.
    """
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert result.system_prompt.startswith("You are Aura.")
    assert "好感度状态" in result.system_prompt  # affinity section present
    assert result.section_count == 3  # persona + affinity + improvised_chat


@pytest.mark.asyncio
async def test_persona_plus_overlay():
    """Persona + affinity + runtime personality overlay + improvised chat = 4 sections."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {"personality_overlay": "当前情绪：保持积极愉快的语气"},
    }
    result = await compile_prompt(state)
    assert "You are Aura." in result.system_prompt
    assert "当前情绪：保持积极愉快的语气" in result.system_prompt
    assert result.section_count == 4  # persona + affinity + overlay + improvised_chat


@pytest.mark.asyncio
async def test_memory_present():
    """Memory context is included when present."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state, memory_context="## 相关记忆\n- 用户喜欢编程")
    assert "用户喜欢编程" in result.system_prompt
    assert result.memory_included is True


@pytest.mark.asyncio
async def test_memory_absent():
    """Memory section omitted when no context."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state, memory_context="")
    assert result.memory_included is False


@pytest.mark.asyncio
async def test_memory_failure_produces_warning():
    """Memory source failure is captured as warning, prompt still compiles."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    # No memory, but prompt still works
    assert "You are Aura." in result.system_prompt
    assert result.section_count >= 1


@pytest.mark.asyncio
async def test_streaming_mode():
    """Streaming mode overlay is included."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"personality_mode": "streaming"},
    }
    result = await compile_prompt(state)
    assert "直播模式" in result.system_prompt


@pytest.mark.asyncio
async def test_trusted_proactive_turn_uses_only_the_dedicated_prompt_source() -> None:
    result = await compile_prompt(
        {
            "session_id": "live",
            "system_prompt": "Base persona.",
            "metadata": {
                "source": "bilibili:proactive_topic",
                "actor_role": "host",
                "audience": "livestream",
                "proactive_topic_seed": {
                    "kind": "scene",
                    "subject": "企鹅",
                    "provenance": "scene_runtime",
                },
                "proactive_topic_max_chars": 36,
                "proactive_recent_outputs": ["鲨鱼生活在海里，因为陆地很难游泳。"],
                "affinity": 99,
            },
        },
        memory_context="## 相关记忆\n- 不应注入主动话题",
    )

    assert "proactive_topic" in result.section_names
    assert "企鹅" in result.system_prompt
    assert "最多 36 字" in result.system_prompt
    assert "鲨鱼生活在海里" in result.system_prompt
    assert "即兴闲聊模式" not in result.system_prompt
    assert "好感度状态" not in result.system_prompt
    assert "相关记忆" not in result.system_prompt


@pytest.mark.asyncio
async def test_minecraft_narration_prompt_uses_only_public_fact_and_persona() -> None:
    result = await compile_prompt(
        {
            "session_id": "minecraft-live",
            "system_prompt": "Base persona.",
            "metadata": {
                "source": "minecraft:narration",
                "actor_role": "host",
                "audience": "livestream",
                "proactive_topic_seed": {
                    "kind": "minecraft_activity",
                    "subject": "我正在确认橡木是否真的收集完成。",
                    "provenance": "minecraft_public_activity",
                },
                "proactive_topic_max_chars": 60,
                "affinity": 99,
            },
        },
        memory_context="## 私有记忆\n- 绝不能进入旁白",
    )

    assert "Minecraft 事实旁白" in result.system_prompt
    assert "我正在确认橡木是否真的收集完成" in result.system_prompt
    assert "最多 60 字" in result.system_prompt
    assert "机器逻辑短路" not in result.system_prompt
    assert "好感度状态" not in result.system_prompt
    assert "私有记忆" not in result.system_prompt


@pytest.mark.asyncio
async def test_forged_proactive_metadata_does_not_activate_dedicated_prompt() -> None:
    result = await compile_prompt(
        {
            "session_id": "live",
            "system_prompt": "Base persona.",
            "metadata": {
                "source": "bilibili:proactive_topic",
                "actor_role": "viewer",
                "audience": "livestream",
            },
        }
    )

    assert "proactive_topic" not in result.section_names
    assert "improvised_chat" in result.section_names


@pytest.mark.asyncio
async def test_mood_overlay():
    """Mood-based overlay is included."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"personality_mood": "happy"},
    }
    result = await compile_prompt(state)
    assert "保持积极愉快的语气" in result.system_prompt


@pytest.mark.asyncio
async def test_improvised_chat_section_present_by_default():
    """Realtime Anima prompt should explicitly avoid stiff repeated templates."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "即兴闲聊模式" in result.system_prompt
    assert "不要复用最近回复的开头" in result.system_prompt
    assert "improvised_chat" in result.section_names


@pytest.mark.asyncio
async def test_config_version_metadata_flows_into_compiled_prompt():
    """CompiledPrompt exposes the runtime config version used for this turn."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"config_version": 7},
    }
    result = await compile_prompt(state)
    assert result.config_version == 7


@pytest.mark.asyncio
async def test_active_service_context_config_overrides_state_prompt():
    """Runtime service context config is the source of truth for persona prompt."""

    class RuntimeConfig:
        def get_system_prompt(self, live2d_prompt: str | None = None) -> str:
            return f"CONFIG-PROMPT::{live2d_prompt or 'NO-LIVE2D'}"

    class ServiceContext:
        config = RuntimeConfig()
        runtime_config_version = 11

    state = {
        "session_id": "test",
        "system_prompt": "STATE-PROMPT",
        "metadata": {},
    }

    result = await compile_prompt(
        state,
        config={"configurable": {"service_context": ServiceContext()}},
    )

    assert "CONFIG-PROMPT" in result.system_prompt
    assert "STATE-PROMPT" not in result.system_prompt


@pytest.mark.asyncio
async def test_state_prompt_is_fallback_without_service_context_config():
    """Isolated prompt compilation still accepts state system_prompt."""
    state = {
        "session_id": "test",
        "system_prompt": "STATE-FALLBACK-PROMPT",
        "metadata": {},
    }

    result = await compile_prompt(state, config={"configurable": {}})

    assert "STATE-FALLBACK-PROMPT" in result.system_prompt


@pytest.mark.asyncio
async def test_live2d_prompt_is_included_from_runtime_config(monkeypatch: pytest.MonkeyPatch):
    """Base persona prompt includes the generated Live2D expression guide."""

    class RuntimeConfig:
        def get_system_prompt(self, live2d_prompt: str | None = None) -> str:
            return f"CONFIG-PROMPT::{live2d_prompt or 'NO-LIVE2D'}"

    class ServiceContext:
        config = RuntimeConfig()
        runtime_config_version = 12

    class Live2DConfig:
        enabled = True
        valid_emotions = ["happy"]

    class Live2DPromptBuilder:
        def build_prompt(self) -> str:
            return "LIVE2D-PROMPT"

    from animetta.avatar.prompts import PerformancePromptBuilder

    monkeypatch.setattr("animetta.config.live2d.get_live2d_config", lambda: Live2DConfig())
    monkeypatch.setattr(
        PerformancePromptBuilder,
        "__new__",
        staticmethod(lambda cls, *args, **kwargs: Live2DPromptBuilder()),
    )

    state = {
        "session_id": "test",
        "system_prompt": "STATE-PROMPT",
        "metadata": {},
    }

    result = await compile_prompt(
        state,
        config={"configurable": {"service_context": ServiceContext()}},
    )

    assert "CONFIG-PROMPT::LIVE2D-PROMPT" in result.system_prompt


@pytest.mark.asyncio
async def test_live2d_prompt_failure_keeps_prompt_and_warns(monkeypatch: pytest.MonkeyPatch):
    """Live2D prompt errors do not block persona prompt compilation."""

    class RuntimeConfig:
        def get_system_prompt(self, live2d_prompt: str | None = None) -> str:
            return f"CONFIG-PROMPT::{live2d_prompt or 'NO-LIVE2D'}"

    class ServiceContext:
        config = RuntimeConfig()
        runtime_config_version = 13

    class Live2DConfig:
        enabled = True
        valid_emotions = ["happy"]

    from animetta.avatar.prompts import PerformancePromptBuilder

    def fail_builder(cls, *args, **kwargs):
        raise RuntimeError("live2d boom")

    monkeypatch.setattr("animetta.config.live2d.get_live2d_config", lambda: Live2DConfig())
    monkeypatch.setattr(PerformancePromptBuilder, "__new__", staticmethod(fail_builder))

    state = {
        "session_id": "test",
        "system_prompt": "STATE-PROMPT",
        "metadata": {},
    }

    result = await compile_prompt(
        state,
        config={"configurable": {"service_context": ServiceContext()}},
    )

    assert "CONFIG-PROMPT::NO-LIVE2D" in result.system_prompt
    assert any("live2d" in warning.lower() for warning in result.warnings)


@pytest.mark.asyncio
async def test_service_context_runtime_config_version_flows_into_compiled_prompt():
    """Runtime config version falls back to active service context metadata."""

    class RuntimeConfig:
        def get_system_prompt(self, live2d_prompt: str | None = None) -> str:
            return "CONFIG-PROMPT"

    class ServiceContext:
        config = RuntimeConfig()
        runtime_config_version = 14

    state = {
        "session_id": "test",
        "system_prompt": "STATE-PROMPT",
        "metadata": {},
    }

    result = await compile_prompt(
        state,
        config={"configurable": {"service_context": ServiceContext()}},
    )

    assert result.config_version == 14


@pytest.mark.asyncio
async def test_section_names_in_metadata():
    """Metadata includes section names."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "persona" in result.section_names


# ── Affinity overlay tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_affinity_section_appears():
    """A fresh state always includes an affinity section (default 50)."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "好感度状态" in result.system_prompt
    assert "当前对家人的好感度: 50/100" in result.system_prompt
    assert "affinity" in result.section_names


@pytest.mark.asyncio
async def test_affinity_value_from_metadata():
    """Affinity value flows from metadata into the prompt."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"affinity": 82},
    }
    result = await compile_prompt(state)
    assert "当前对家人的好感度: 82/100" in result.system_prompt
    assert "亲近" in result.system_prompt  # band for 71-85


@pytest.mark.asyncio
async def test_affinity_section_ordering():
    """Affinity (priority 150) renders after persona (100), before overlay (200)."""
    state = {
        "session_id": "test",
        "system_prompt": "[PERSONA-BLOCK]",
        "metadata": {
            "affinity": 60,
            "personality_overlay": "[OVERLAY-BLOCK]",
        },
    }
    result = await compile_prompt(state)
    persona_pos = result.system_prompt.index("[PERSONA-BLOCK]")
    affinity_pos = result.system_prompt.index("好感度状态")
    overlay_pos = result.system_prompt.index("[OVERLAY-BLOCK]")
    assert persona_pos < affinity_pos < overlay_pos, (
        f"ordering wrong: persona={persona_pos}, affinity={affinity_pos}, overlay={overlay_pos}"
    )


@pytest.mark.asyncio
async def test_affinity_band_text_changes_with_value():
    """Different affinity values produce different band labels in the prompt."""
    bands = {}
    for value, expected_substring in [
        (15, "警惕疏离"),
        (45, "礼貌"),
        (62, "略熟"),
        (78, "亲近"),
        (92, "宠溺"),
    ]:
        state = {
            "session_id": "test",
            "system_prompt": "Base.",
            "metadata": {"affinity": value},
        }
        result = await compile_prompt(state)
        assert expected_substring in result.system_prompt, (
            f"value={value} should mention {expected_substring!r}"
        )
        bands[value] = expected_substring
    # Sanity: bands are actually different across the range
    assert len(set(bands.values())) == 5


@pytest.mark.asyncio
async def test_affinity_clamped_to_display_range():
    """Out-of-range affinity values are clamped for display (no crash)."""
    for raw_value in [-50, 200]:
        state = {
            "session_id": "test",
            "system_prompt": "Base.",
            "metadata": {"affinity": raw_value},
        }
        result = await compile_prompt(state)
        # Clamped to [0, 100], prompt still compiles
        assert "当前对家人的好感度:" in result.system_prompt


# ── Live improvisation section tests (task 1.5) ──────────────────


@pytest.mark.asyncio
async def test_improvisation_section_included_and_named():
    """Live improvisation section is present with stable name."""
    state = {
        "session_id": "test",
        "system_prompt": "Base persona.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "improvised_chat" in result.section_names
    assert "即兴闲聊模式" in result.system_prompt


@pytest.mark.asyncio
async def test_improvisation_ordered_before_memory():
    """Live improvisation (priority 225) appears before memory (priority 300)."""
    state = {
        "session_id": "test",
        "system_prompt": "[PERSONA]",
        "metadata": {},
    }
    result = await compile_prompt(state, memory_context="## 相关记忆\n用户喜欢猫")
    improv_pos = result.system_prompt.index("即兴闲聊模式")
    memory_pos = result.system_prompt.index("相关记忆")
    assert improv_pos < memory_pos, (
        f"improvisation ({improv_pos}) should come before memory ({memory_pos})"
    )


@pytest.mark.asyncio
async def test_improvisation_discourages_customer_service_phrasing():
    """The section should explicitly forbid assistant/customer-service phrases."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    prompt = result.system_prompt
    # Should contain explicit prohibitions
    assert "禁止" in prompt
    assert "客服" in prompt or "当然可以" in prompt


@pytest.mark.asyncio
async def test_improvisation_promotes_short_anima_replies():
    """The section should promote short replies with Anima voice anchors."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    prompt = result.system_prompt
    # Should mention style anchors
    assert "Anima" in prompt or "毒舌" in prompt or "慵懒" in prompt


@pytest.mark.asyncio
async def test_improvisation_preserves_persona_verbal_tics():
    """Improvisation must not override persona-specific suffixes or口癖."""
    state = {
        "session_id": "test",
        "system_prompt": "Base persona says every sentence ends with 喵.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    prompt = result.system_prompt
    assert "基础人设" in prompt
    assert "口癖" in prompt
    assert "句尾后缀" in prompt


@pytest.mark.asyncio
async def test_persona_and_affinity_unchanged_after_improvisation():
    """Persona, affinity, and runtime sections remain deterministic."""
    state = {
        "session_id": "test",
        "system_prompt": "[FIXED-PERSONA]",
        "metadata": {"affinity": 65},
    }
    result = await compile_prompt(state)
    # Persona still present unchanged
    assert "[FIXED-PERSONA]" in result.system_prompt
    # Affinity still present
    assert "好感度状态" in result.system_prompt
    assert "65/100" in result.system_prompt
    # Both appear before improvisation
    persona_pos = result.system_prompt.index("[FIXED-PERSONA]")
    improv_pos = result.system_prompt.index("即兴闲聊模式")
    assert persona_pos < improv_pos


def _scene_guidance(**overrides):
    guidance = {
        "scene_revision": 3,
        "scene_summary": "观众正在围绕穿模形成共同笑点。",
        "response_objective": "接住笑点并在两句内收住，不切换话题。",
        "tone": ["playful", "quick"],
        "scope": {
            "max_sentences": 2,
            "max_chars": 120,
            "allow_topic_switch": False,
            "audience_target": "whole_room",
        },
        "must_address": ["回应付费事件"],
        "avoid": ["不要重复已经过热的梗"],
        "technique": {
            "technique_id": "callback",
            "instruction": "用一句回扣主播刚才的失误。",
        },
        "meme_policy": {
            "action": "use",
            "meme_id": "clipping",
            "instruction": "只轻点一次穿模梗。",
        },
        "confidence": 0.9,
        "expires_at": time.time() + 60,
    }
    guidance.update(overrides)
    return guidance


async def test_valid_scene_guidance_replaces_generic_improvisation() -> None:
    result = await compile_prompt(
        {
            "session_id": "live",
            "system_prompt": "Base.",
            "metadata": {"scene_guidance": _scene_guidance()},
        }
    )

    assert "scene_guidance" in result.section_names
    assert "improvised_chat" not in result.section_names
    assert "直播场景导演建议" in result.system_prompt
    assert "接住笑点并在两句内收住" in result.system_prompt
    assert "用一句回扣主播刚才的失误" in result.system_prompt
    assert "只轻点一次穿模梗" in result.system_prompt
    assert '"scene_revision"' not in result.system_prompt


async def test_scripted_scene_scope_replaces_streaming_eighteen_character_limit() -> None:
    result = await compile_prompt(
        {
            "session_id": "program",
            "system_prompt": "Base.",
            "metadata": {
                "personality_mode": "streaming",
                "scene_guidance": _scene_guidance(
                    response_objective="组合复述四个记忆槽位。",
                    scope={
                        "max_sentences": 4,
                        "max_chars": 160,
                        "allow_topic_switch": False,
                        "audience_target": "current_viewer",
                    },
                ),
            },
        }
    )

    assert "最多 4 句、160 字" in result.system_prompt
    assert "不超过18个字" not in result.system_prompt


async def test_scene_meme_policy_suppresses_recalled_meme_documents() -> None:
    result = await compile_prompt(
        {
            "session_id": "live",
            "system_prompt": "Base.",
            "metadata": {
                "scene_guidance": _scene_guidance(
                    meme_policy={
                        "action": "avoid",
                        "instruction": "让已经饱和的梗休息。",
                    }
                )
            },
        },
        memory_context=(
            "## 相关记忆\n- 观众喜欢短回复\n\n"
            "## 活跃梗\n- 继续反复使用穿模梗\n\n"
            "## 用户画像\n- 偏好: 轻松"
        ),
    )

    assert "观众喜欢短回复" in result.system_prompt
    assert "偏好: 轻松" in result.system_prompt
    assert "活跃梗" not in result.system_prompt
    assert "继续反复使用穿模梗" not in result.system_prompt
    assert "本轮不要主动用梗" in result.system_prompt


@pytest.mark.parametrize(
    "guidance",
    [
        {"unexpected": "document"},
        _scene_guidance(expires_at=1),
    ],
)
async def test_malformed_or_expired_guidance_is_contained(guidance) -> None:
    result = await compile_prompt(
        {
            "session_id": "live",
            "system_prompt": "Base.",
            "metadata": {"scene_guidance": guidance},
        }
    )

    assert "scene_guidance" not in result.section_names
    assert "improvised_chat" in result.section_names
    assert "即兴闲聊模式" in result.system_prompt
    assert any("scene guidance" in warning.lower() for warning in result.warnings)

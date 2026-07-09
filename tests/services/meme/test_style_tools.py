from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from animetta.services.meme.styles import (
    MemeRouter,
    MemeState,
    MemeStyleValidationError,
    ZhouliTool,
    build_style_prompt_section,
    decorate_response,
    get_meme_style,
    parse_meme_invocation,
)


def test_zhouli_style_registry_exposes_template_and_rules():
    style = get_meme_style("zhouli")

    assert style is not None
    assert "meme:zhouli" in style.aliases
    assert "吾闻" in style.aliases
    assert "古人云" in style.aliases
    assert "先王制礼" in style.aliases
    assert "周礼体" in style.aliases
    assert [slot.name for slot in style.slots] == [
        "modern_event",
        "surface_behavior",
        "elevated_interpretation",
        "other_action",
        "ordinary_behavior",
        "noble_interpretation",
    ]
    assert "medical" in style.avoid_scenes
    assert style.cooldown_turns == 3
    assert style.max_per_window == 2


def test_zhouli_tool_renders_complete_slots_under_max_chars():
    tool = ZhouliTool()

    result = tool.render(
        {
            "modern_event": "今日不欲上工",
            "surface_behavior": "怠惰",
            "elevated_interpretation": "身心求养以全后日之功",
            "other_action": "暂得休养",
            "ordinary_behavior": "偷闲",
            "noble_interpretation": "养其精神以全其职",
        },
        max_chars=180,
    )

    assert result.success is True
    assert result.style == "zhouli"
    assert result.mode == "quip"
    assert "吾闻" in result.text
    assert "并非" in result.text
    assert "乃是" in result.text
    assert "看似怠惰" in result.text
    assert "实则身心求养以全后日之功" in result.text
    assert "此岂不合乎周礼？" in result.text
    assert len(result.text) <= 180


def test_zhouli_tool_reports_missing_slots():
    tool = ZhouliTool()

    with pytest.raises(MemeStyleValidationError) as exc:
        tool.render({"modern_event": "今日不欲上工"})

    assert "surface_behavior" in exc.value.missing_slots
    assert "noble_interpretation" in exc.value.missing_slots


def test_prompt_section_is_explanation_first_and_contains_few_shots():
    prompt = build_style_prompt_section([get_meme_style("zhouli")])

    assert prompt.index("周礼体") < prompt.index("slots")
    assert "疯狂星期四" in prompt
    assert "不想上班" in prompt
    assert "不要写成纯文言" in prompt
    assert "format_id" in prompt
    assert "format_slots" in prompt


@pytest.mark.asyncio
async def test_zhouli_tool_generates_from_natural_language_intent_without_llm():
    result = await ZhouliTool().run("今天不想上班", mode="quip", max_chars=180)

    assert result.success is True
    assert result.style == "zhouli"
    assert result.format_id == "zhouli"
    assert result.format_slots["modern_event"] == "今天不想上班"
    assert "今天不想上班" in result.text
    assert "此岂不合乎周礼？" in result.text


@pytest.mark.asyncio
async def test_zhouli_tool_uses_llm_slot_filling_when_available():
    llm = AsyncMock()
    llm.chat_messages.return_value = {
        "content": (
            '{"modern_event":"疯狂星期四求一鸡","surface_behavior":"贪嘴",'
            '"elevated_interpretation":"给诸友修仁义结善缘",'
            '"other_action":"有人愿以鸡相赠","ordinary_behavior":"破费",'
            '"noble_interpretation":"以食通礼以礼会友"}'
        )
    }

    result = await ZhouliTool(llm_client=llm).run("疯狂星期四", max_chars=180)

    assert result.success is True
    assert result.format_slots["surface_behavior"] == "贪嘴"
    assert "以食通礼" in result.text
    llm.chat_messages.assert_awaited_once()


def test_parse_meme_invocation_accepts_zhouli_command():
    invocation = parse_meme_invocation("meme:zhouli 今天不想上班")

    assert invocation is not None
    assert invocation.style_id == "zhouli"
    assert invocation.intent == "今天不想上班"
    assert invocation.is_explicit is True


def test_router_blocks_serious_scenes_and_allows_explicit():
    router = MemeRouter()
    state = MemeState()

    assert router.route(
        "上班好累",
        mood="light_complaint",
        scene="mental_health",
        state=state,
        turn_index=1,
        semi_active_enabled=True,
    ).action == "none"

    explicit = router.route(
        "meme:zhouli 上班好累",
        mood="light_complaint",
        scene="mental_health",
        state=state,
        turn_index=2,
        semi_active_enabled=True,
    )
    assert explicit.action == "explicit"
    assert explicit.bypass_cooldown is True


def test_router_enforces_cooldown_and_window_cap():
    router = MemeRouter()
    state = MemeState()

    first = router.route(
        "上班好累",
        mood="light_complaint",
        scene="chat",
        state=state,
        turn_index=10,
        semi_active_enabled=True,
    )
    assert first.action == "semi_active"
    state.record_use("zhouli", 10)

    second = router.route(
        "不想开会",
        mood="light_complaint",
        scene="chat",
        state=state,
        turn_index=12,
        semi_active_enabled=True,
    )
    assert second.action == "none"
    assert second.reason == "cooldown"

    state.record_use("zhouli", 14)
    capped = router.route(
        "代码又炸了",
        mood="light_complaint",
        scene="chat",
        state=state,
        turn_index=20,
        semi_active_enabled=True,
    )
    assert capped.action == "none"
    assert capped.reason == "window_cap"


@pytest.mark.asyncio
async def test_decorate_response_appends_one_zhouli_quip_for_light_complaint():
    state = MemeState()

    decorated = await decorate_response(
        user_text="上班好累",
        response_text="工牌吸魂这种事，现代企业一般不承认。",
        mood="light_complaint",
        scene="chat",
        state=state,
        turn_index=1,
        semi_active_enabled=True,
    )

    assert decorated.used_style == "zhouli"
    assert decorated.text.startswith("工牌吸魂这种事")
    assert "此岂不合乎周礼？" in decorated.text


@pytest.mark.asyncio
async def test_decorate_response_leaves_serious_context_unchanged():
    state = MemeState()
    response = "先把症状和持续时间记录下来，我们再一步步看。"

    decorated = await decorate_response(
        user_text="我最近很焦虑",
        response_text=response,
        mood="light_complaint",
        scene="mental_health",
        state=state,
        turn_index=1,
        semi_active_enabled=True,
    )

    assert decorated.used_style is None
    assert decorated.text == response

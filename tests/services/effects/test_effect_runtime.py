"""Tests for the workflow-first expression effect runtime."""

from __future__ import annotations

import pytest

from animetta.services.effects import (
    EffectPlan,
    EffectPlanner,
    EffectRuntime,
    ResponsePlan,
    create_default_effect_runtime,
)


@pytest.mark.asyncio
async def test_default_runtime_executes_explicit_zhouli_as_performance_event():
    runtime = create_default_effect_runtime()
    response = await runtime.run(
        ResponsePlan(
            input_text="meme:zhouli 今天不想上班",
            main_text="",
            scene="light_banter",
            effects=[
                EffectPlan(
                    id="meme:zhouli",
                    target_text="今天不想上班",
                    mode="full_reply",
                    position="replace",
                    intensity=2,
                    explicit=True,
                )
            ],
        )
    )

    assert response.text
    assert "今天不想上班" in response.text
    assert "此岂不合乎周礼？" in response.text
    assert response.effects[0].id == "meme:zhouli"
    assert response.effects[0].success is True
    assert response.effects[0].format_id == "zhouli"
    assert response.effects[0].events
    assert {event.type for event in response.effects[0].events} >= {
        "voice",
        "face",
        "overlay",
    }

    metadata = response.to_metadata()
    assert metadata["response_plan"]["scene"] == "light_banter"
    assert metadata["response_plan"]["effects"][0]["id"] == "meme:zhouli"
    assert metadata["effects"][0]["id"] == "meme:zhouli"
    assert metadata["effect_events"][0]["type"] in {"voice", "face", "overlay"}


@pytest.mark.asyncio
async def test_runtime_composes_ending_quip_after_main_reply():
    runtime = create_default_effect_runtime()
    response = await runtime.run(
        ResponsePlan(
            input_text="今天不想上班",
            main_text="先歇一口气，我懂这种电量见底的感觉。",
            scene="light_complaint",
            effects=[
                EffectPlan(
                    id="meme:zhouli",
                    target_text="今天不想上班",
                    mode="ending_quip",
                    position="after_main_reply",
                    intensity=2,
                )
            ],
        )
    )

    assert response.text.startswith("先歇一口气")
    assert "\n\n" in response.text
    assert response.text.endswith("此岂不合乎周礼？")
    assert response.effects[0].position == "after_main_reply"


@pytest.mark.asyncio
async def test_runtime_blocks_non_explicit_meme_in_serious_scene():
    runtime = create_default_effect_runtime()
    response = await runtime.run(
        ResponsePlan(
            input_text="我今天真的很崩溃",
            main_text="我在，先别急着把自己推到极限。",
            scene="mental_health",
            effects=[
                EffectPlan(
                    id="meme:zhouli",
                    target_text="我今天真的很崩溃",
                    mode="ending_quip",
                    position="after_main_reply",
                    intensity=2,
                    explicit=False,
                )
            ],
        )
    )

    assert response.text == "我在，先别急着把自己推到极限。"
    assert response.effects[0].success is False
    assert response.effects[0].safety["allowed"] is False
    assert response.effects[0].safety["reason"] == "blocked_scene"
    assert response.to_metadata()["effects"][0]["safety"]["allowed"] is False


@pytest.mark.asyncio
async def test_runtime_marks_unknown_effect_as_failed_without_changing_reply():
    runtime = EffectRuntime()
    response = await runtime.run(
        ResponsePlan(
            input_text="hello",
            main_text="hello back",
            effects=[
                EffectPlan(
                    id="meme:missing",
                    target_text="hello",
                    mode="ending_quip",
                    position="after_main_reply",
                )
            ],
        )
    )

    assert response.text == "hello back"
    assert response.effects[0].success is False
    assert response.effects[0].error == "unknown_effect"


def test_planner_turns_explicit_meme_command_into_response_plan():
    plan = EffectPlanner().plan(
        user_text="meme:zhouli 疯狂星期四",
        main_text="",
        scene="chat",
        mood="neutral",
    )

    assert plan.scene == "explicit_meme"
    assert plan.reply_goal == "render_requested_meme_style"
    assert plan.effects[0].id == "meme:zhouli"
    assert plan.effects[0].target_text == "疯狂星期四"
    assert plan.effects[0].position == "replace"
    assert plan.effects[0].explicit is True


def test_planner_can_create_semi_active_ending_quip_plan():
    plan = EffectPlanner().plan(
        user_text="今天不想上班",
        main_text="先接住你的疲惫。",
        scene="chat",
        mood="light_complaint",
        semi_active_enabled=True,
        turn_index=3,
    )

    assert plan.main_text == "先接住你的疲惫。"
    assert plan.effects[0].id == "meme:zhouli"
    assert plan.effects[0].mode == "ending_quip"
    assert plan.effects[0].position == "after_main_reply"
    assert plan.effects[0].explicit is False


def test_planner_does_not_plan_semi_active_meme_for_serious_scene():
    plan = EffectPlanner().plan(
        user_text="我今天真的很崩溃",
        main_text="我在，先把呼吸放慢。",
        scene="mental_health",
        mood="light_complaint",
        semi_active_enabled=True,
        turn_index=3,
    )

    assert plan.effects == []
    assert plan.forbidden == ["meme:zhouli"]

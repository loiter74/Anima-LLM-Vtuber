from __future__ import annotations

from animetta.config import ReplyPolicyConfig
from animetta.services.bilibili.models import DanmakuMessage
from animetta.services.bilibili.reply_admission import (
    ReplyAdmissionController,
    ReplyPriority,
)


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _message(text: str, *, user_id: int = 1, timestamp: float = 100.0, **flags):
    return DanmakuMessage(
        text=text,
        user_id=user_id,
        timestamp=timestamp,
        **flags,
    )


def _controller(
    *,
    clock: MutableClock | None = None,
    random_value: float = 0.0,
    **overrides,
) -> ReplyAdmissionController:
    values = {
        "max_replies_per_minute": 6,
        "per_user_cooldown_seconds": 0,
        "duplicate_window_seconds": 0,
        "ordinary_sample_rate": 0.0,
    }
    values.update(overrides)
    config = ReplyPolicyConfig(**values)
    return ReplyAdmissionController(
        config,
        clock=clock or MutableClock(),
        random_source=lambda: random_value,
    )


def test_question_is_soft_weighted_without_ordinary_sampling() -> None:
    controller = _controller(ordinary_sample_rate=0.0)

    decision = controller.decide(_message("为什么天空是蓝色的？"))

    assert decision.admitted is True
    assert decision.priority is ReplyPriority.QUESTION
    assert decision.reason is None


def test_character_name_mention_does_not_change_ordinary_admission() -> None:
    mentioned = _controller(ordinary_sample_rate=1.0, random_value=0.5)
    unmentioned = _controller(ordinary_sample_rate=1.0, random_value=0.5)

    with_name = mentioned.decide(_message("Animetta 今天真精神"))
    without_name = unmentioned.decide(_message("今天真精神"))

    assert with_name.admitted == without_name.admitted is True
    assert with_name.priority == without_name.priority is ReplyPriority.ORDINARY


def test_duplicate_and_per_user_cooldown_have_distinct_drop_reasons() -> None:
    duplicate_controller = _controller(
        duplicate_window_seconds=30,
        ordinary_sample_rate=1.0,
    )
    assert duplicate_controller.decide(_message("重复内容", user_id=1)).admitted
    duplicate = duplicate_controller.decide(_message("重复内容", user_id=2))

    cooldown_controller = _controller(
        per_user_cooldown_seconds=30,
        ordinary_sample_rate=1.0,
    )
    assert cooldown_controller.decide(_message("第一条", user_id=9)).admitted
    cooldown = cooldown_controller.decide(_message("第二条", user_id=9))

    assert duplicate.reason == "duplicate"
    assert cooldown.reason == "user_cooldown"


def test_token_bucket_exhausts_and_refills_with_injected_clock() -> None:
    clock = MutableClock()
    controller = _controller(
        clock=clock,
        max_replies_per_minute=1,
        ordinary_sample_rate=1.0,
    )

    assert controller.decide(_message("第一条", user_id=1)).admitted
    limited = controller.decide(_message("第二条", user_id=2))
    clock.value += 60
    refilled = controller.decide(
        _message("第三条", user_id=3, timestamp=clock.value),
    )

    assert limited.reason == "rate_limited"
    assert refilled.admitted is True


def test_sampling_and_expiry_are_deterministic() -> None:
    clock = MutableClock(100)
    controller = _controller(
        clock=clock,
        random_value=0.9,
        ordinary_sample_rate=0.1,
        max_message_age_seconds=10,
    )

    not_sampled = controller.decide(_message("普通消息", timestamp=100))
    expired = controller.decide(_message("过期问题吗？", timestamp=89, user_id=2))

    assert not_sampled.reason == "not_sampled"
    assert expired.reason == "expired"


def test_super_chat_and_gift_have_highest_priorities() -> None:
    controller = _controller()

    super_chat = controller.decide(
        _message("醒目留言", user_id=1, is_super_chat=True),
    )
    gift = controller.decide(_message("赠送礼物", user_id=2, is_gift=True))

    assert super_chat.priority is ReplyPriority.SUPER_CHAT
    assert gift.priority is ReplyPriority.GIFT


def test_disabled_policy_rejects_without_consuming_budget() -> None:
    controller = ReplyAdmissionController(
        ReplyPolicyConfig(enabled=False),
        clock=MutableClock(),
    )

    decision = controller.decide(_message("为什么？"))

    assert decision.admitted is False
    assert decision.reason == "disabled"


def test_exhaustive_mode_admits_every_valid_message_without_selective_filters() -> None:
    controller = _controller(
        mode="exhaustive",
        max_replies_per_minute=1,
        per_user_cooldown_seconds=3600,
        duplicate_window_seconds=3600,
        ordinary_sample_rate=0.0,
        max_message_age_seconds=1,
    )

    decisions = [
        controller.decide(_message("同一条普通弹幕", user_id=7, timestamp=0)) for _ in range(10)
    ]

    assert all(decision.admitted for decision in decisions)
    assert controller.admitted_count == 10

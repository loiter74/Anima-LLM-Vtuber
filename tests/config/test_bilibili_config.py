"""Contracts for Bilibili livestream configuration."""

import pytest
from pydantic import ValidationError

from animetta.config.providers.bilibili import BilibiliConfig, ReplyPolicyConfig


def test_reply_policy_defaults_are_bounded_and_safe() -> None:
    policy = ReplyPolicyConfig()

    assert policy.enabled is True
    assert policy.mode == "selective"
    assert policy.max_replies_per_minute == 6
    assert policy.max_queue_size == 20
    assert policy.generation_concurrency == 1
    assert policy.max_message_age_seconds == 15
    assert policy.per_user_cooldown_seconds == 30
    assert policy.duplicate_window_seconds == 60
    assert policy.ordinary_sample_rate == 0.1
    assert policy.reply_to_gifts is True
    assert policy.reply_to_super_chat is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_replies_per_minute", 0),
        ("max_queue_size", 0),
        ("generation_concurrency", 0),
        ("max_message_age_seconds", 0),
        ("per_user_cooldown_seconds", -1),
        ("duplicate_window_seconds", -1),
        ("ordinary_sample_rate", -0.01),
        ("ordinary_sample_rate", 1.01),
    ],
)
def test_reply_policy_rejects_out_of_range_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        ReplyPolicyConfig.model_validate({field: value})


def test_existing_bilibili_config_gets_default_reply_policy() -> None:
    config = BilibiliConfig.model_validate(
        {"enabled": True, "room_id": 12345, "sessdata": "secret-cookie"}
    )

    assert config.reply_policy == ReplyPolicyConfig()


def test_public_config_excludes_sessdata() -> None:
    config = BilibiliConfig(
        enabled=True,
        room_id=12345,
        sessdata="secret-cookie",
    )

    public = config.to_public_dict()

    assert public["enabled"] is True
    assert public["room_id"] == 12345
    assert public["reply_policy"]["max_queue_size"] == 20
    assert "sessdata" not in public

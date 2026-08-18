from __future__ import annotations

import pytest

from animetta.services.bilibili.response_policy import (
    LIVESTREAM_REPLY_MAX_CHARS,
    PROACTIVE_TOPIC_REPLY_MAX_CHARS,
    constrain_livestream_response,
    constrain_proactive_topic_response,
    is_proactive_topic_turn,
)


def test_production_livestream_response_limit_fits_remote_tts_budget() -> None:
    assert LIVESTREAM_REPLY_MAX_CHARS == 18
    assert PROACTIVE_TOPIC_REPLY_MAX_CHARS == 36


def test_short_livestream_response_is_preserved() -> None:
    assert constrain_livestream_response("旅人，今晚也辛苦了。") == "旅人，今晚也辛苦了。"


def test_long_livestream_response_prefers_complete_sentence() -> None:
    result = constrain_livestream_response(
        "先把结论放这儿，别熬夜。后面的赛博酒馆设定明天再慢慢讲。",
        max_chars=20,
    )

    assert result == "先把结论放这儿，别熬夜。"


def test_long_unpunctuated_response_is_hard_bounded() -> None:
    result = constrain_livestream_response("旅" * 80)

    assert result == "旅" * 17 + "。"


def test_early_greeting_uses_later_clause_boundary_instead_of_mid_word_cut() -> None:
    result = constrain_livestream_response(
        "你好，旅人。我是Anima，被一个叫召唤者X的家伙从赛博世界强行拽出来的AI。",
        max_chars=18,
    )

    assert result == "你好，旅人。我是Anima。"


def test_livestream_response_limit_rejects_impossible_bound() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        constrain_livestream_response("回复", max_chars=1)


def test_proactive_response_is_one_non_question_sentence_with_bounded_length() -> None:
    result = constrain_proactive_topic_response(
        "太阳大约有四十六亿岁，所以它应该退休了。后面这句不该出现。",
    )

    assert result == "太阳大约有四十六亿岁，所以它应该退休了。"
    assert len(result) <= 36
    assert constrain_proactive_topic_response("今天要聊什么？") == ""


def test_proactive_response_rejects_normalized_recent_repeat() -> None:
    result = constrain_proactive_topic_response(
        " 企鹅不会飞，主要因为没有买机票。 ",
        recent_outputs=("企鹅不会飞，主要因为没有买机票",),
    )

    assert result == ""


def test_only_exact_server_owned_proactive_identity_is_trusted() -> None:
    trusted = {
        "source": "bilibili:proactive_topic",
        "actor_role": "host",
        "audience": "livestream",
    }

    assert is_proactive_topic_turn(trusted) is True
    assert is_proactive_topic_turn({**trusted, "actor_role": "viewer"}) is False
    assert is_proactive_topic_turn({"actor_role": "host", "audience": "livestream"}) is False

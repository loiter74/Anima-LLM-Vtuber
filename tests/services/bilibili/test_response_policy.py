from __future__ import annotations

import pytest

from animetta.services.bilibili.response_policy import (
    LIVESTREAM_REPLY_MAX_CHARS,
    constrain_livestream_response,
)


def test_production_livestream_response_limit_fits_remote_tts_budget() -> None:
    assert LIVESTREAM_REPLY_MAX_CHARS == 18


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

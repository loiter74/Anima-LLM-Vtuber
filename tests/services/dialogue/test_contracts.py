from __future__ import annotations

import pytest

from animetta.services.dialogue.contracts import (
    ComposerResult,
    DialogueParseError,
    ReasonerResult,
    parse_composer_result,
    parse_reasoner_result,
)


def test_reasoner_requires_all_fields() -> None:
    with pytest.raises(DialogueParseError) as exc:
        parse_reasoner_result('{"normal_response":"你好","stance":"友好","humor":""}')
    assert exc.value.code == "schema_invalid"


def test_reasoner_accepts_required_empty_optional_directions() -> None:
    result = parse_reasoner_result(
        '{"normal_response":"你好。","stance":"温和但直接","humor":"","worldview":""}'
    )
    assert result == ReasonerResult(
        normal_response="你好。", stance="温和但直接", humor="", worldview=""
    )


@pytest.mark.parametrize("raw", ["not json", "[]", '{"normal_response":'])
def test_reasoner_rejects_invalid_json(raw: str) -> None:
    with pytest.raises(DialogueParseError) as exc:
        parse_reasoner_result(raw)
    assert exc.value.code == "invalid_json"


def test_reasoner_enforces_bounds() -> None:
    raw = '{"normal_response":"' + ("字" * 2001) + '","stance":"x","humor":"","worldview":""}'
    with pytest.raises(DialogueParseError) as exc:
        parse_reasoner_result(raw)
    assert exc.value.code == "schema_invalid"


@pytest.mark.parametrize("marker", ["<|assistant|>", "```json", "[SYSTEM]"])
def test_authored_responses_reject_runtime_markers(marker: str) -> None:
    raw = '{"final_response":"你好 ' + marker + '","mood":"neutral","affinity_delta":0}'
    with pytest.raises(DialogueParseError) as exc:
        parse_composer_result(raw)
    assert exc.value.code == "leaked_marker"


def test_composer_enforces_mood_and_affinity_bounds() -> None:
    with pytest.raises(DialogueParseError):
        parse_composer_result('{"final_response":"你好","mood":"excited","affinity_delta":3}')
    result = parse_composer_result('{"final_response":"你好","mood":"bright","affinity_delta":-2}')
    assert result == ComposerResult(final_response="你好", mood="bright", affinity_delta=-2)


def test_parse_error_excerpt_is_bounded_and_does_not_echo_secrets() -> None:
    secret = "sk-secret-value"
    with pytest.raises(DialogueParseError) as exc:
        parse_reasoner_result("not-json " + secret + ("x" * 500))
    assert len(exc.value.safe_excerpt) <= 80
    assert secret not in exc.value.safe_excerpt

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.smoke_real_profile import SmokeGateError, validate_readiness_payload


def _ready_payload() -> dict:
    identities = {
        "llm": ("deepseek", "deepseek", "deepseek-v4-flash", None),
        "asr": ("mimo", "mimo", "mimo-v2.5-asr", None),
        "tts": ("mimo", "mimo", "mimo-v2.5-tts", "mimo_default"),
        "vad": ("mimo", "mimo", "mimo-v2.5-asr", None),
    }
    components = {}
    for category, (provider_type, provider, model, voice) in identities.items():
        identity = {
            "type": provider_type,
            "provider": provider,
            "model": model,
            "voice": voice,
        }
        components[category] = {
            "ready": True,
            "configured": dict(identity),
            "resolved": dict(identity),
            "reason": None,
        }
    return {
        "ready": True,
        "profile": "smoke",
        "version": 1,
        "effective_hash": "a" * 64,
        "semantic_hash": "b" * 64,
        "components": components,
    }


def test_e2e_s004_accepts_distinct_matching_real_provider_rows() -> None:
    summary = validate_readiness_payload(_ready_payload())

    assert summary["profile"] == "smoke"
    assert summary["providers"]["asr"]["model"] == "mimo-v2.5-asr"
    assert summary["providers"]["tts"]["model"] == "mimo-v2.5-tts"
    assert "configured" not in summary["providers"]["tts"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(ready=False),
        lambda payload: payload.update(profile="test"),
        lambda payload: payload["components"]["tts"]["resolved"].update(
            voice="other"
        ),
        lambda payload: payload["components"]["asr"]["resolved"].update(
            type="mock", provider="mock", model="mock"
        ),
    ],
)
def test_e2e_s004_rejects_unready_mismatched_or_mock_status(mutation) -> None:
    payload = deepcopy(_ready_payload())
    mutation(payload)

    with pytest.raises(SmokeGateError):
        validate_readiness_payload(payload)

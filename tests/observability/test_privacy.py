from animetta.observability.domain import PrivacyMode
from animetta.observability.privacy import ObservationContentPolicy


def test_development_profile_defaults_to_full_content() -> None:
    policy = ObservationContentPolicy.for_profile("development", salt="test-salt")

    facts = policy.content_facts("你好")

    assert policy.mode is PrivacyMode.FULL
    assert facts.text == "你好"
    assert facts.character_count == 2
    assert facts.byte_count == 6
    assert len(facts.digest) == 64


def test_golden_and_production_profiles_default_to_redacted_content() -> None:
    golden = ObservationContentPolicy.for_profile("golden", salt="test-salt")
    production = ObservationContentPolicy.for_profile("production", salt="test-salt")

    golden_facts = golden.content_facts("不要落库")
    production_facts = production.content_facts("不要落库")

    assert golden.mode is production.mode is PrivacyMode.REDACTED
    assert golden_facts.text is None
    assert production_facts.text is None
    assert golden_facts.digest == production_facts.digest


def test_different_installation_salts_produce_different_digests() -> None:
    first = ObservationContentPolicy(PrivacyMode.REDACTED, salt="install-a")
    second = ObservationContentPolicy(PrivacyMode.REDACTED, salt="install-b")

    assert first.content_facts("same").digest != second.content_facts("same").digest


def test_event_attributes_drop_sensitive_and_large_payload_fields() -> None:
    policy = ObservationContentPolicy(PrivacyMode.FULL, salt="test")

    filtered = policy.filter_attributes(
        {
            "provider": "deepseek",
            "model": "v4-flash",
            "payload_size": 1024,
            "audio_data": "base64-secret",
            "volumes": [0.1, 0.2],
            "authorization": "Bearer token",
            "prompt": "internal prompt",
            "arbitrary": "not allowlisted",
        }
    )

    assert filtered == {
        "provider": "deepseek",
        "model": "v4-flash",
        "payload_size": 1024,
    }


def test_error_summary_redacts_tokens_and_is_bounded() -> None:
    policy = ObservationContentPolicy(PrivacyMode.FULL, salt="test")

    error = policy.sanitize_error(
        "request failed Authorization: Bearer abcdef123456 api_key=secret-value " + "x" * 500,
        error_type="network_error",
    )

    assert error.error_type == "network_error"
    assert "abcdef123456" not in error.summary
    assert "secret-value" not in error.summary
    assert len(error.summary) <= 200

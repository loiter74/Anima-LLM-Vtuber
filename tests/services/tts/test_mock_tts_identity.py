from animetta.config.providers.tts.mock import MockTTSConfig
from animetta.services.tts.mock_tts import MockTTS


def test_from_config_preserves_readiness_identity() -> None:
    tts = MockTTS.from_config(MockTTSConfig(voice="default"))

    assert tts.resolved_identity == {
        "type": "mock",
        "provider": "mock",
        "model": None,
        "voice": "default",
    }

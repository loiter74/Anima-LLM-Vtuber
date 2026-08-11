from animetta.config.providers.vad import MockVADConfig
from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import PrivacyMode
from animetta.observability.ports import NoOpObservationRecorder
from animetta.observability.service_proxy import InstrumentedServiceProxy
from animetta.services.asr import ASRFactory
from animetta.services.llm import LLMFactory
from animetta.services.tts import TTSFactory
from animetta.services.vad import VADFactory


class Recorder(NoOpObservationRecorder):
    def __init__(self) -> None:
        self.started = []

    async def start_operation(self, record) -> None:
        self.started.append(record)


def test_core_service_factories_use_recorder_backed_proxy() -> None:
    recorder = NoOpObservationRecorder()

    services = [
        LLMFactory.create("mock", observation_recorder=recorder),
        TTSFactory.create("mock", observation_recorder=recorder),
        ASRFactory.create("mock", observation_recorder=recorder),
        VADFactory.create_from_config(MockVADConfig(), observation_recorder=recorder),
    ]

    assert all(isinstance(service, InstrumentedServiceProxy) for service in services)


async def test_remote_tts_observation_uses_declared_provider_identity(monkeypatch) -> None:
    from animetta.services.tts.remote_tts import RemoteTTS

    async def synthesize(_self, _text, **_kwargs):
        return b"RIFF"

    monkeypatch.setattr(RemoteTTS, "synthesize", synthesize)
    recorder = Recorder()
    service = TTSFactory.create(
        "remote",
        provider="test-provider",
        model="test-model",
        voice="test-voice",
        base_url="http://127.0.0.1:8767",
        observation_recorder=recorder,
    )
    context = ObservationContext(
        trace_id="task-1",
        operation_id="tts-node",
        parent_operation_id=None,
        message_id="message-1",
        conversation_id="conversation-1",
        session_id="session-1",
        privacy_mode=PrivacyMode.FULL,
    )

    with observation_context(context):
        await service.synthesize("你好")

    assert recorder.started[0].provider == "test-provider"

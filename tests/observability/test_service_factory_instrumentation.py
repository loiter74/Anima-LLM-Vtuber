from animetta.config.providers.vad import MockVADConfig
from animetta.observability.ports import NoOpObservationRecorder
from animetta.observability.service_proxy import InstrumentedServiceProxy
from animetta.services.asr import ASRFactory
from animetta.services.llm import LLMFactory
from animetta.services.tts import TTSFactory
from animetta.services.vad import VADFactory


def test_core_service_factories_use_recorder_backed_proxy() -> None:
    recorder = NoOpObservationRecorder()

    services = [
        LLMFactory.create("mock", observation_recorder=recorder),
        TTSFactory.create("mock", observation_recorder=recorder),
        ASRFactory.create("mock", observation_recorder=recorder),
        VADFactory.create_from_config(
            MockVADConfig(), observation_recorder=recorder
        ),
    ]

    assert all(isinstance(service, InstrumentedServiceProxy) for service in services)

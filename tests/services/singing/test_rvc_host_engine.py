from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch

from animetta.host_rvc_contract import HostRVCContract
from animetta_rvc_host import host as rvc_host
from animetta_rvc_host.engine import TransformersHubertAdapter


class FakeHubertModel:
    def __init__(self) -> None:
        self.hidden_states = tuple(torch.full((1, 2, 3), index) for index in range(13))
        self.calls: list[dict[str, Any]] = []

    def __call__(self, source: torch.Tensor, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"source": source, **kwargs})
        return SimpleNamespace(hidden_states=self.hidden_states)

    def to(self, _device: Any) -> FakeHubertModel:
        return self

    def half(self) -> FakeHubertModel:
        return self

    def float(self) -> FakeHubertModel:
        return self

    def eval(self) -> FakeHubertModel:
        return self


def test_transformers_hubert_adapter_matches_rvc_feature_contract() -> None:
    model = FakeHubertModel()
    adapter = TransformersHubertAdapter(model=model)
    source = torch.ones((1, 320), dtype=torch.float32)
    padding_mask = torch.zeros_like(source, dtype=torch.bool)

    features = adapter.extract_features(
        source=source,
        padding_mask=padding_mask,
        output_layer=12,
    )

    assert torch.equal(features[0], model.hidden_states[12])
    assert torch.equal(model.calls[0]["attention_mask"], torch.ones_like(source, dtype=torch.long))
    assert model.calls[0]["output_hidden_states"] is True
    assert model.calls[0]["return_dict"] is True


def test_host_rvc_loads_and_publishes_the_pinned_feature_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = tmp_path / "assets" / "weights" / "tosaka.pth"
    index = tmp_path / "logs" / "tosaka.index"
    hubert = tmp_path / "hubert" / "pytorch_model.bin"
    rmvpe = tmp_path / "assets" / "rmvpe" / "rmvpe.pt"
    for path, payload in (
        (model, b"model"),
        (index, b"index"),
        (hubert, b"hubert"),
        (rmvpe, b"rmvpe"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    captured: dict[str, Any] = {}

    class FakeEngine:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeSeparator:
        def __init__(self, **_kwargs: Any) -> None:
            pass

    monkeypatch.setenv("QWEN_TTS_API_KEY", "secret")
    monkeypatch.setattr(rvc_host, "RVCInferenceEngine", FakeEngine)
    monkeypatch.setattr(rvc_host, "DemucsHostSeparator", FakeSeparator)
    contract = HostRVCContract(
        provider="rvc-webui-host",
        model=model.name,
        revision="release-revision",
        voice="tosaka-rin-cn",
        sample_rate=48000,
        timeout_seconds=1200.0,
        runtime_root=tmp_path,
        python_executable=tmp_path / "python.exe",
        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        index_path=Path("logs") / index.name,
        index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),
        hubert_model_dir=hubert.parent,
        hubert_sha256=hashlib.sha256(hubert.read_bytes()).hexdigest(),
        hubert_repo="local/hubert",
        hubert_revision="hubert-revision",
        rmvpe_sha256=hashlib.sha256(rmvpe.read_bytes()).hexdigest(),
        device="cuda:0",
        is_half=False,
        separation_model="htdemucs",
        separation_python_executable=tmp_path / "demucs-python.exe",
        separation_device="cuda",
        separation_timeout_seconds=1200.0,
    )

    service = rvc_host.build_host_service_from_env(contract)

    assert captured["index_path"] == index
    assert service.settings.index == index.name
    assert service.settings.index_revision == contract.index_sha256

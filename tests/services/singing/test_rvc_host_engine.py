from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import torch

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

"""GPU RVC engine using a Transformers HuBERT compatibility boundary."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import soundfile as sf
import torch


class TransformersHubertAdapter:
    """Expose a local Transformers HuBERT model through RVC's Fairseq API."""

    def __init__(self, model_dir: Path | None = None, *, model: Any | None = None) -> None:
        if model is None:
            if model_dir is None:
                raise ValueError("HuBERT model directory is required")
            from transformers import HubertModel

            model = HubertModel.from_pretrained(
                str(model_dir),
                local_files_only=True,
            )
        self.model = model

    def to(self, device: Any) -> TransformersHubertAdapter:
        self.model.to(device)
        return self

    def half(self) -> TransformersHubertAdapter:
        self.model.half()
        return self

    def float(self) -> TransformersHubertAdapter:
        self.model.float()
        return self

    def eval(self) -> TransformersHubertAdapter:
        self.model.eval()
        return self

    def extract_features(
        self,
        *,
        source: torch.Tensor,
        padding_mask: torch.Tensor | None,
        output_layer: int,
    ) -> tuple[torch.Tensor]:
        attention_mask = None if padding_mask is None else (~padding_mask).long()
        output = self.model(
            source,
            attention_mask=attention_mask,
            output_hidden_states=True,
            return_dict=True,
        )
        hidden_states = output.hidden_states
        if hidden_states is None or output_layer >= len(hidden_states):
            raise RuntimeError(f"HuBERT output layer is unavailable: {output_layer}")
        return (hidden_states[output_layer],)


def install_fairseq_compat(model_dir: Path) -> None:
    """Install only the checkpoint loader API used by the pinned RVC runtime."""

    checkpoint_utils = ModuleType("fairseq.checkpoint_utils")

    def load_model_ensemble_and_task(
        _paths: list[str],
        *,
        suffix: str = "",
    ) -> tuple[list[TransformersHubertAdapter], None, None]:
        del suffix
        return [TransformersHubertAdapter(model_dir)], None, None

    checkpoint_utils.load_model_ensemble_and_task = load_model_ensemble_and_task  # type: ignore[attr-defined]
    fairseq = ModuleType("fairseq")
    fairseq.checkpoint_utils = checkpoint_utils  # type: ignore[attr-defined]
    sys.modules["fairseq"] = fairseq
    sys.modules["fairseq.checkpoint_utils"] = checkpoint_utils


class RVCInferenceEngine:
    """Own one loaded RVC voice model and serialize GPU conversion calls."""

    def __init__(
        self,
        *,
        runtime_root: Path,
        model_name: str,
        hubert_model_dir: Path,
        index_path: Path | None = None,
        device: str = "cuda:0",
        is_half: bool = False,
    ) -> None:
        self.runtime_root = runtime_root.resolve()
        self.model_name = model_name
        self.hubert_model_dir = hubert_model_dir.resolve()
        self.index_path = index_path.resolve() if index_path else None
        self.device = device
        self.is_half = is_half
        self._vc: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def model_path(self) -> Path:
        return self.runtime_root / "assets" / "weights" / self.model_name

    async def preload(self) -> None:
        if self._vc is None:
            await asyncio.to_thread(self._load)

    def _load(self) -> None:
        required = (
            self.runtime_root,
            self.model_path,
            self.hubert_model_dir / "config.json",
            self.hubert_model_dir / "pytorch_model.bin",
            self.runtime_root / "assets" / "rmvpe" / "rmvpe.pt",
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise RuntimeError("RVC asset(s) missing: " + ", ".join(missing))

        os.environ["weight_root"] = str(self.model_path.parent)  # noqa: SIM112
        os.environ["index_root"] = str(self.runtime_root / "logs")  # noqa: SIM112
        os.environ["rmvpe_root"] = str(self.runtime_root / "assets" / "rmvpe")  # noqa: SIM112
        if str(self.runtime_root) not in sys.path:
            sys.path.insert(0, str(self.runtime_root))
        install_fairseq_compat(self.hubert_model_dir)

        from configs.config import Config
        from infer.modules.vc.modules import VC

        use_cuda = self.device.startswith("cuda") and torch.cuda.is_available()
        config = Config()
        config.device = self.device if use_cuda else "cpu"
        config.is_half = self.is_half and use_cuda
        config.use_jit = False
        config.dml = False
        vc = VC(config)
        vc.get_vc(self.model_name)
        self._vc = vc

    async def convert(
        self,
        audio: bytes,
        *,
        f0_method: str = "rmvpe",
        f0_up_key: int = 0,
        index_rate: float = 0.0,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.5,
        protect: float = 0.5,
    ) -> bytes:
        await self.preload()
        async with self._lock:
            return await asyncio.to_thread(
                self._convert,
                audio,
                f0_method,
                f0_up_key,
                index_rate,
                filter_radius,
                rms_mix_rate,
                protect,
            )

    def _convert(
        self,
        audio: bytes,
        f0_method: str,
        f0_up_key: int,
        index_rate: float,
        filter_radius: int,
        rms_mix_rate: float,
        protect: float,
    ) -> bytes:
        vc = self._vc
        if vc is None:
            raise RuntimeError("RVC engine is not preloaded")
        temp_root = self.runtime_root / "TEMP"
        temp_root.mkdir(parents=True, exist_ok=True)
        input_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".wav",
                dir=temp_root,
                delete=False,
            ) as source:
                source.write(audio)
                input_path = Path(source.name)
            file_index = (
                str(self.index_path) if self.index_path and self.index_path.is_file() else ""
            )
            _message, result = vc.vc_single(
                0,
                str(input_path),
                f0_up_key,
                None,
                f0_method,
                file_index,
                None,
                index_rate,
                filter_radius,
                0,
                rms_mix_rate,
                protect,
            )
            if not isinstance(result, tuple) or len(result) != 2 or result[1] is None:
                raise RuntimeError("RVC returned no converted audio")
            sample_rate, samples = result
            output = io.BytesIO()
            sf.write(output, np.asarray(samples), int(sample_rate), format="WAV", subtype="PCM_16")
            converted = output.getvalue()
            if len(converted) <= 44:
                raise RuntimeError("RVC returned an empty WAV")
            return converted
        finally:
            if input_path is not None:
                input_path.unlink(missing_ok=True)

    async def close(self) -> None:
        self._vc = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

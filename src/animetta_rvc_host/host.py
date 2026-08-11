"""Build the fixed host RVC service from its shared runtime contract."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from animetta.host_rvc_contract import HOST_RVC_CONTRACT, HostRVCContract

from .app import RVCService, RVCServiceSettings
from .engine import RVCInferenceEngine
from .separator import DemucsHostSeparator


def _require_hash(path: Path, expected: str, label: str) -> None:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except OSError as error:
        raise RuntimeError(f"Host RVC {label} is unavailable") from error
    if actual != expected.upper():
        raise RuntimeError(f"Host RVC {label} identity mismatch")


def build_host_service_from_env(
    contract: HostRVCContract = HOST_RVC_CONTRACT,
) -> RVCService:
    runtime_root = Path(os.getenv("RVC_HOST_RUNTIME_ROOT", str(contract.runtime_root)))
    model_path = runtime_root / "assets" / "weights" / contract.model
    hubert_model_dir = Path(os.getenv("RVC_HOST_HUBERT_MODEL_DIR", str(contract.hubert_model_dir)))
    _require_hash(model_path, contract.model_sha256, "voice model")
    _require_hash(
        hubert_model_dir / "pytorch_model.bin",
        contract.hubert_sha256,
        "HuBERT model",
    )
    _require_hash(
        runtime_root / "assets" / "rmvpe" / "rmvpe.pt",
        contract.rmvpe_sha256,
        "RMVPE model",
    )
    settings = RVCServiceSettings(
        api_key=os.getenv("QWEN_TTS_API_KEY", ""),
        provider=contract.provider,
        model=contract.model,
        revision=contract.revision,
        voice=contract.voice,
        sample_rate=contract.sample_rate,
        conversion_timeout_seconds=contract.timeout_seconds,
        separation_model=contract.separation_model,
    )
    engine = RVCInferenceEngine(
        runtime_root=runtime_root,
        model_name=contract.model,
        hubert_model_dir=hubert_model_dir,
        device=os.getenv("RVC_HOST_DEVICE", contract.device),
        is_half=contract.is_half,
    )
    project_root = Path(__file__).resolve().parents[2]
    separator = DemucsHostSeparator(
        python_executable=contract.separation_python_executable,
        wrapper_path=project_root / "scripts" / "demucs_fix.py",
        model=contract.separation_model,
        device=contract.separation_device,
        temp_root=runtime_root / "TEMP" / "animetta-separation",
        timeout_seconds=contract.separation_timeout_seconds,
    )
    return RVCService(settings, engine, separator)

"""Single source of truth shared by Animetta and the Windows host RVC worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_HOST_RVC_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "host-rvc.yaml"


@dataclass(frozen=True, slots=True)
class HostRVCContract:
    provider: str
    model: str
    revision: str
    voice: str
    sample_rate: int
    timeout_seconds: float
    runtime_root: Path
    python_executable: Path
    model_sha256: str
    index_path: Path | None
    index_sha256: str | None
    hubert_model_dir: Path
    hubert_sha256: str
    hubert_repo: str
    hubert_revision: str
    rmvpe_sha256: str
    device: str
    is_half: bool
    separation_model: str
    separation_python_executable: Path
    separation_device: str
    separation_timeout_seconds: float

    def identity(self) -> dict[str, str | int]:
        identity: dict[str, str | int] = {
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "voice": self.voice,
            "sample_rate": self.sample_rate,
        }
        if self.index_path is not None and self.index_sha256 is not None:
            identity["index"] = self.index_path.name
            identity["index_revision"] = self.index_sha256
        return identity


def load_host_rvc_contract(
    path: str | Path = DEFAULT_HOST_RVC_CONTRACT_PATH,
) -> HostRVCContract:
    contract_path = Path(path)
    try:
        raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Invalid host RVC contract: {contract_path}") from error
    root = _mapping(raw, "root")
    if root.get("schema_version") != 1:
        raise RuntimeError("Host RVC contract schema_version must be 1")
    identity = _mapping(root.get("identity"), "identity")
    client = _mapping(root.get("client"), "client")
    runtime = _mapping(root.get("runtime"), "runtime")
    separation = _mapping(root.get("separation"), "separation")
    is_half = runtime.get("is_half")
    if not isinstance(is_half, bool):
        raise RuntimeError("Host RVC contract is_half must be boolean")
    index_path_text = _optional_text(runtime, "index_path")
    index_sha256 = _optional_text(runtime, "index_sha256")
    if (index_path_text is None) != (index_sha256 is None):
        raise RuntimeError(
            "Host RVC contract runtime index_path and index_sha256 must be configured together"
        )
    return HostRVCContract(
        provider=_text(identity, "provider"),
        model=_text(identity, "model"),
        revision=_text(identity, "revision"),
        voice=_text(identity, "voice"),
        sample_rate=_positive_int(identity, "sample_rate"),
        timeout_seconds=_positive_float(client, "timeout_seconds"),
        runtime_root=Path(_text(runtime, "root")),
        python_executable=Path(_text(runtime, "python")),
        model_sha256=_text(runtime, "model_sha256").upper(),
        index_path=Path(index_path_text) if index_path_text is not None else None,
        index_sha256=index_sha256.upper() if index_sha256 is not None else None,
        hubert_model_dir=Path(_text(runtime, "hubert_model_dir")),
        hubert_sha256=_text(runtime, "hubert_sha256").upper(),
        hubert_repo=_text(runtime, "hubert_repo"),
        hubert_revision=_text(runtime, "hubert_revision"),
        rmvpe_sha256=_text(runtime, "rmvpe_sha256").upper(),
        device=_text(runtime, "device"),
        is_half=is_half,
        separation_model=_text(separation, "model"),
        separation_python_executable=Path(_text(separation, "python")),
        separation_device=_text(separation, "device"),
        separation_timeout_seconds=_positive_float(separation, "timeout_seconds"),
    )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Host RVC contract {field} must be a mapping")
    return value


def _text(values: dict[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Host RVC contract {field} must be a non-empty string")
    return value.strip()


def _optional_text(values: dict[str, Any], field: str) -> str | None:
    value = values.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Host RVC contract {field} must be a non-empty string")
    return value.strip()


def _positive_int(values: dict[str, Any], field: str) -> int:
    value = values.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Host RVC contract {field} must be a positive integer")
    return value


def _positive_float(values: dict[str, Any], field: str) -> float:
    value = values.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Host RVC contract {field} must be positive")
    return float(value)


HOST_RVC_CONTRACT = load_host_rvc_contract()

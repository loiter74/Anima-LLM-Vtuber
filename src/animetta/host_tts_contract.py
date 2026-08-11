"""Single source of truth shared by Animetta and the Windows host TTS worker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_HOST_TTS_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "host-tts.yaml"


@dataclass(frozen=True, slots=True)
class HostTTSContract:
    provider: str
    model: str
    revision: str
    quantization: str
    runtime_commit: str
    voice: str
    sample_rate: int
    response_format: str
    language: str
    timeout_seconds: float
    model_dir: Path
    reference_audio: Path
    reference_sha256: str
    reference_text: str

    def identity(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "quantization": self.quantization,
            "runtime_commit": self.runtime_commit,
            "voice": self.voice,
            "sample_rate": self.sample_rate,
        }

    def remote_declaration(self) -> dict[str, str | float]:
        return {
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "quantization": self.quantization,
            "runtime_commit": self.runtime_commit,
            "voice": self.voice,
            "response_format": self.response_format,
            "language": self.language,
            "timeout_seconds": self.timeout_seconds,
        }


def load_host_tts_contract(
    path: str | Path = DEFAULT_HOST_TTS_CONTRACT_PATH,
) -> HostTTSContract:
    contract_path = Path(path)
    try:
        raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RuntimeError(f"Invalid host TTS contract: {contract_path}") from error
    root = _mapping(raw, "root")
    if root.get("schema_version") != 1:
        raise RuntimeError("Host TTS contract schema_version must be 1")
    identity = _mapping(root.get("identity"), "identity")
    client = _mapping(root.get("client"), "client")
    runtime = _mapping(root.get("runtime"), "runtime")
    return HostTTSContract(
        provider=_text(identity, "provider"),
        model=_text(identity, "model"),
        revision=_text(identity, "revision"),
        quantization=_text(identity, "quantization"),
        runtime_commit=_text(identity, "runtime_commit"),
        voice=_text(identity, "voice"),
        sample_rate=_positive_int(identity, "sample_rate"),
        response_format=_text(client, "response_format"),
        language=_text(client, "language"),
        timeout_seconds=_positive_float(client, "timeout_seconds"),
        model_dir=Path(_text(runtime, "model_dir")),
        reference_audio=Path(_text(runtime, "reference_audio")),
        reference_sha256=_text(runtime, "reference_sha256").upper(),
        reference_text=_text(runtime, "reference_text"),
    )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Host TTS contract {field} must be a mapping")
    return value


def _text(values: dict[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Host TTS contract {field} must be a non-empty string")
    return value.strip()


def _positive_int(values: dict[str, Any], field: str) -> int:
    value = values.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Host TTS contract {field} must be a positive integer")
    return value


def _positive_float(values: dict[str, Any], field: str) -> float:
    value = values.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"Host TTS contract {field} must be positive")
    return float(value)


HOST_TTS_CONTRACT = load_host_tts_contract()

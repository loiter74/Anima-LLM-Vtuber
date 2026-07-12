"""Fail-closed, offline checks for the July golden runtime profile."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import wave
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlsplit

GOLDEN_QWEN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
GOLDEN_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
GOLDEN_QWEN_REQUIRED_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "speech_tokenizer/config.json",
    "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
)
_GOLDEN_QWEN_JSON_FILES = tuple(
    path for path in GOLDEN_QWEN_REQUIRED_FILES if path.endswith(".json")
)
_GOLDEN_QWEN_SAFETENSORS_FILES = tuple(
    path for path in GOLDEN_QWEN_REQUIRED_FILES if path.endswith(".safetensors")
)

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
)
_SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"\bapi[ _-]?key\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(
        r"[A-Za-z0-9_-]*(?:token|password|secret|authorization|api[_-]?key)"
        r"[A-Za-z0-9_-]*\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
)
_URL_PATTERN = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)


def _default_cuda_probe() -> Mapping[str, Any]:
    """Inspect CUDA lazily so importing this module never imports torch."""
    try:
        torch = importlib.import_module("torch")
        available = bool(torch.cuda.is_available())
        if not available:
            return {"available": False, "reason": "torch reports CUDA unavailable"}
        device_count = int(torch.cuda.device_count())
        device_name = str(torch.cuda.get_device_name(0)) if device_count else "unknown"
        return {
            "available": True,
            "device_count": device_count,
            "device_name": device_name,
        }
    except Exception as exc:  # pragma: no cover - exercised through injected probes
        return {"available": False, "reason": str(exc)}


def _default_dependency_probe(module_name: str) -> Mapping[str, Any]:
    """Check an installed dependency without importing the dependency itself."""
    available = importlib.util.find_spec(module_name) is not None
    result: dict[str, Any] = {"available": available}
    if available:
        package_name = module_name.replace("_", "-")
        try:
            result["version"] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            result["version"] = "unknown"
    return result


@dataclass(frozen=True)
class GoldenPreflightContext:
    """Replaceable local probes and paths used by :func:`run_golden_preflight`."""

    scope: Literal["runtime", "static"] = "runtime"
    project_root: Path = field(default_factory=Path.cwd)
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    cuda_probe: Callable[[], Mapping[str, Any]] = _default_cuda_probe
    dependency_probe: Callable[[str], Mapping[str, Any]] = _default_dependency_probe
    live2d_model_path: str | None = None
    runtime_engines: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous scopes instead of silently weakening runtime checks."""
        if self.scope not in {"runtime", "static"}:
            raise ValueError("scope must be 'runtime' or 'static'")


@dataclass(frozen=True)
class GoldenPreflightCheck:
    """One stable, machine-readable preflight assertion."""

    name: str
    ok: bool
    code: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class GoldenPreflightReport:
    """Complete preflight result with sanitized evidence."""

    ok: bool
    scope: Literal["runtime", "static"]
    acceptance_ready: bool
    checks: tuple[GoldenPreflightCheck, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible payload."""
        return {
            "ok": self.ok,
            "scope": self.scope,
            "acceptance_ready": self.acceptance_ready,
            "checks": [
                {
                    "name": check.name,
                    "ok": check.ok,
                    "code": check.code,
                    "detail": check.detail,
                }
                for check in self.checks
            ],
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize the report deterministically for readiness and evidence tools."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    segments = {segment for segment in normalized.split("_") if segment}
    return (
        bool({"token", "secret", "password", "authorization"} & segments)
        or "api_key" in normalized
        or "apikey" in segments
        or any(
            normalized == part or normalized.endswith(f"_{part}")
            for part in _SENSITIVE_KEY_PARTS
        )
    )


def _secret_values(config: Any, env: Mapping[str, str]) -> tuple[str, ...]:
    values = {
        str(value)
        for key, value in env.items()
        if _is_sensitive_key(key) and value and len(str(value)) >= 4
    }
    configured_key = getattr(
        getattr(getattr(config, "agent", None), "llm_config", None),
        "api_key",
        None,
    )
    if configured_key and len(str(configured_key)) >= 4:
        values.add(str(configured_key))
    return tuple(sorted(values, key=len, reverse=True))


def _safe_url_for_diagnostic(value: str) -> str:
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname or ""
        if not scheme or not hostname:
            return "<redacted-url>"
        safe_host = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            safe_host = f"{safe_host}:{port}"
        return f"{scheme}://{safe_host}{parsed.path}"
    except (TypeError, ValueError):
        return "<redacted-url>"


def _sanitize(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if _is_sensitive_key(key) else _sanitize(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, Path):
        return _sanitize(str(value), secrets)
    if isinstance(value, str):
        sanitized = _URL_PATTERN.sub(
            lambda match: _safe_url_for_diagnostic(match.group(0)),
            value,
        )
        for secret in secrets:
            sanitized = sanitized.replace(secret, "<redacted>")
        for pattern in _SECRET_PATTERNS:
            sanitized = pattern.sub("<redacted>", sanitized)
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize(str(value), secrets)


def _attribute(value: Any, *names: str, default: Any = None) -> Any:
    current = value
    for name in names:
        if current is None:
            return default
        current = getattr(current, name, None)
    return default if current is None else current


def _present(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and not (text.startswith("${") and text.endswith("}")))


def _resolve_project_path(project_root: Path, configured_path: str | None) -> Path | None:
    if not configured_path:
        return None
    path = Path(configured_path)
    return path if path.is_absolute() else project_root / path


def _reference_audio_evidence(path: Path | None) -> tuple[bool, str, dict[str, Any]]:
    if path is None or not path.is_file():
        return False, "reference_audio_missing", {"path_present": path is not None}
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, "reference_audio_invalid", {"reason": str(exc)}
    if size == 0:
        return False, "reference_audio_empty", {"size_bytes": 0}
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            frame_count = audio.getnframes()
    except (EOFError, OSError, wave.Error) as exc:
        return False, "reference_audio_invalid", {"reason": str(exc)}
    if channels <= 0 or sample_rate <= 0 or frame_count <= 0:
        return False, "reference_audio_invalid", {"reason": "WAV contains no playable frames"}
    return True, "ok", {
        "size_bytes": size,
        "channels": channels,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
    }


def _json_mapping_is_valid(path: Path, relative_path: str) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return False
    if not isinstance(payload, dict) or not payload:
        return False
    if relative_path == "config.json":
        return "model_type" in payload or "architectures" in payload
    if relative_path == "speech_tokenizer/config.json":
        return "model_type" in payload or "architectures" in payload
    return True


def _safetensors_is_valid(path: Path) -> bool:
    try:
        file_size = path.stat().st_size
        if not path.is_file() or file_size <= 9:
            return False
        with path.open("rb") as stream:
            header_size_raw = stream.read(8)
            if len(header_size_raw) != 8:
                return False
            header_size = int.from_bytes(header_size_raw, "little", signed=False)
            if header_size <= 2 or header_size > min(file_size - 8, 16 * 1024 * 1024):
                return False
            header_raw = stream.read(header_size)
        header = json.loads(header_raw.decode("utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
        return False
    if not isinstance(header, dict):
        return False

    data_size = file_size - 8 - header_size
    tensors = [(name, value) for name, value in header.items() if name != "__metadata__"]
    if not tensors:
        return False
    data_ranges: list[tuple[int, int]] = []
    for _name, tensor in tensors:
        if not isinstance(tensor, dict):
            return False
        dtype = tensor.get("dtype")
        shape = tensor.get("shape")
        offsets = tensor.get("data_offsets")
        if (
            not isinstance(dtype, str)
            or not dtype
            or not isinstance(shape, list)
            or not all(isinstance(dimension, int) and dimension >= 0 for dimension in shape)
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(offset, int) for offset in offsets)
        ):
            return False
        start, end = offsets
        if start < 0 or end <= start or end > data_size:
            return False
        data_ranges.append((start, end))
    cursor = 0
    for start, end in sorted(data_ranges):
        if start != cursor:
            return False
        cursor = end
    return cursor == data_size


def _shard_index_evidence(snapshot: Path) -> tuple[bool, str, dict[str, Any]]:
    try:
        indexes = sorted(
            path
            for path in snapshot.rglob("*.index.json")
            if path.name.endswith((".safetensors.index.json", ".bin.index.json"))
        )
    except OSError:
        return False, "model_cache_shard_index_invalid", {}
    snapshot_root = snapshot.resolve()
    for index_path in indexes:
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = payload.get("weight_map") if isinstance(payload, dict) else None
        except (json.JSONDecodeError, OSError, UnicodeError):
            weight_map = None
        if not isinstance(weight_map, dict) or not weight_map:
            return False, "model_cache_shard_index_invalid", {
                "index": index_path.relative_to(snapshot).as_posix(),
            }

        shard_values = list(weight_map.values())
        if not all(isinstance(value, str) and value for value in shard_values):
            return False, "model_cache_shard_index_invalid", {
                "index": index_path.relative_to(snapshot).as_posix(),
            }
        shard_names = sorted(set(shard_values))
        missing: list[str] = []
        invalid: list[str] = []
        for shard_name in shard_names:
            shard_path = (index_path.parent / shard_name).resolve()
            if not shard_path.is_relative_to(snapshot_root) or not shard_path.is_file():
                missing.append(shard_name)
                continue
            try:
                nonempty = shard_path.stat().st_size > 0
            except OSError:
                nonempty = False
            if not nonempty:
                missing.append(shard_name)
            elif shard_path.suffix.lower() == ".safetensors" and not _safetensors_is_valid(
                shard_path
            ):
                invalid.append(shard_name)
        if missing:
            return False, "model_cache_shard_missing", {"missing_shards": sorted(missing)}
        if invalid:
            return False, "model_cache_safetensors_invalid", {
                "invalid": sorted(invalid),
            }
    return True, "ok", {"shard_indexes": len(indexes)}


def _snapshot_evidence(snapshot: Path) -> tuple[bool, str, dict[str, Any]]:
    missing = [
        relative_path
        for relative_path in GOLDEN_QWEN_REQUIRED_FILES
        if not (snapshot / relative_path).is_file()
    ]
    if missing:
        return False, "model_cache_required_file_missing", {"missing": missing}

    invalid_json = [
        relative_path
        for relative_path in _GOLDEN_QWEN_JSON_FILES
        if not _json_mapping_is_valid(snapshot / relative_path, relative_path)
    ]
    if invalid_json:
        return False, "model_cache_json_invalid", {"invalid": invalid_json}

    merges_path = snapshot / "merges.txt"
    try:
        merges_valid = bool(merges_path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        merges_valid = False
    if not merges_valid:
        return False, "model_cache_text_invalid", {"invalid": ["merges.txt"]}

    invalid_safetensors = [
        relative_path
        for relative_path in _GOLDEN_QWEN_SAFETENSORS_FILES
        if not _safetensors_is_valid(snapshot / relative_path)
    ]
    if invalid_safetensors:
        return False, "model_cache_safetensors_invalid", {
            "invalid": invalid_safetensors,
        }

    shards_ok, shards_code, shards_detail = _shard_index_evidence(snapshot)
    if not shards_ok:
        return False, shards_code, shards_detail
    return True, "ok", {
        "required_files": len(GOLDEN_QWEN_REQUIRED_FILES),
        **shards_detail,
    }


def _model_cache_evidence(
    model_id: str,
    env: Mapping[str, str],
) -> tuple[bool, str, dict[str, Any], str | None]:
    hf_home_value = env.get("HF_HOME")
    hf_home = Path(hf_home_value) if hf_home_value else Path.home() / ".cache" / "huggingface"
    model_root = hf_home / "hub" / f"models--{model_id.replace('/', '--')}"
    refs_main = model_root / "refs" / "main"
    snapshots_root = model_root / "snapshots"
    base_detail = {
        "model_id": model_id,
        "cache_source": "HF_HOME" if hf_home_value else "default",
    }
    try:
        if not refs_main.is_file():
            return False, "model_cache_ref_missing", {**base_detail, "revision": None}, None
        revision = refs_main.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return False, "model_cache_ref_unreadable", {**base_detail, "revision": None}, None
    if not revision or not re.fullmatch(r"[A-Za-z0-9._-]+", revision) or revision in {".", ".."}:
        return False, "model_cache_ref_invalid", {**base_detail, "revision": None}, None

    try:
        snapshots_root_resolved = snapshots_root.resolve()
        snapshot = (snapshots_root / revision).resolve()
        snapshot_is_active = snapshot.is_relative_to(snapshots_root_resolved)
        snapshot_exists = snapshot.is_dir()
    except OSError:
        snapshot_is_active = False
        snapshot_exists = False
        snapshot = snapshots_root / revision
    if not snapshot_is_active or not snapshot_exists:
        return False, "model_cache_active_snapshot_missing", {
            **base_detail,
            "revision": revision,
        }, None

    valid, code, snapshot_detail = _snapshot_evidence(snapshot)
    detail = {**base_detail, "revision": revision, **snapshot_detail}
    return valid, code, detail, revision if valid else None


def _configured_live2d_path(
    project_root: Path,
) -> tuple[str | None, str | None, dict[str, Any]]:
    config_path = project_root / "config" / "features" / "live2d.yaml"
    if not config_path.is_file():
        return None, None, {}
    try:
        import yaml

        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            return None, "live2d_config_invalid", {"reason": "root_not_mapping"}
        model = payload.get("model")
        if not isinstance(model, Mapping):
            return None, "live2d_config_invalid", {"reason": "model_not_mapping"}
        value = model.get("path")
        if not isinstance(value, str) or not value.strip():
            return None, "live2d_config_invalid", {"reason": "model_path_missing"}
        return value, None, {}
    except Exception as exc:
        return None, "live2d_config_invalid", {"reason": type(exc).__name__}


def _live2d_asset_roots(project_root: Path) -> tuple[Path, Path]:
    public_root = project_root / "frontend" / "public" / "live2d"
    deployed_root = project_root / "frontend" / "dist" / "live2d"
    return public_root, deployed_root


def _frontend_live2d_asset(project_root: Path, relative_path: Path) -> Path:
    public_root, deployed_root = _live2d_asset_roots(project_root)
    public_asset = public_root / relative_path
    return public_asset if public_asset.is_file() else deployed_root / relative_path


def _resolve_live2d_asset(project_root: Path, model_path: str | None) -> Path | None:
    if not model_path:
        return None
    if model_path.startswith("/live2d/"):
        return _frontend_live2d_asset(
            project_root, Path(model_path.removeprefix("/live2d/"))
        )
    path = Path(model_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "live2d":
        return _frontend_live2d_asset(project_root, Path(*path.parts[1:]))
    return project_root / path


def _live2d_asset_evidence(
    asset: Path | None,
    configured_path: str | None,
    allowed_root: Path,
) -> tuple[bool, str, dict[str, Any]]:
    base_detail = {"model_path": configured_path}
    if asset is not None:
        try:
            resolved_asset = asset.resolve()
            resolved_root = allowed_root.resolve()
            if not resolved_asset.is_relative_to(resolved_root):
                return False, "live2d_model_path_outside_root", base_detail
            asset = resolved_asset
        except (OSError, ValueError):
            return False, "live2d_model_path_outside_root", base_detail
    if asset is None or not asset.is_file():
        return False, "live2d_asset_missing", {
            **base_detail,
            "readable_nonempty": False,
        }
    try:
        if not asset.name.endswith(".model3.json") or asset.stat().st_size <= 0:
            return False, "live2d_manifest_invalid", base_detail
        manifest = json.loads(asset.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError):
        return False, "live2d_manifest_invalid", base_detail
    if not isinstance(manifest, dict):
        return False, "live2d_manifest_invalid", base_detail

    references = manifest.get("FileReferences")
    if not isinstance(references, dict):
        return False, "live2d_references_missing", base_detail
    moc = references.get("Moc")
    textures = references.get("Textures")
    if (
        not isinstance(moc, str)
        or not moc.strip()
        or not isinstance(textures, list)
        or not textures
        or not all(isinstance(texture, str) and texture.strip() for texture in textures)
    ):
        return False, "live2d_references_missing", base_detail

    reference_specs = [("moc", moc), *[("texture", texture) for texture in textures]]
    base_dir = asset.parent.resolve()
    invalid: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for kind, relative_path in reference_specs:
        reference_path = Path(relative_path)
        try:
            resolved = (base_dir / reference_path).resolve()
            is_safe_relative = not reference_path.is_absolute() and resolved.is_relative_to(base_dir)
        except (OSError, ValueError):
            is_safe_relative = False
            resolved = base_dir
        if not is_safe_relative:
            invalid.append({"kind": kind, "path": relative_path})
            continue
        try:
            readable_nonempty = resolved.is_file() and resolved.stat().st_size > 0
        except OSError:
            readable_nonempty = False
        if not readable_nonempty:
            missing.append({"kind": kind, "path": relative_path})

    if invalid:
        return False, "live2d_reference_invalid", {**base_detail, "invalid": invalid}
    if missing:
        return False, "live2d_reference_missing", {**base_detail, "missing": missing}
    return True, "ok", {
        **base_detail,
        "readable_nonempty": True,
        "reference_count": len(reference_specs),
    }


def _frontend_dist_evidence(path: Path) -> tuple[bool, str, dict[str, Any]]:
    detail = {"relative_path": "frontend/dist/index.html"}
    try:
        if not path.is_file():
            return False, "frontend_dist_missing", {
                **detail,
                "readable_nonempty": False,
            }
        if path.stat().st_size <= 0:
            return False, "frontend_dist_missing", {
                **detail,
                "readable_nonempty": False,
            }
    except OSError as exc:
        return False, "frontend_dist_unreadable", {
            **detail,
            "readable_nonempty": False,
            "reason": type(exc).__name__,
        }
    return True, "ok", {**detail, "readable_nonempty": True}


def _is_mock_engine(engine: object) -> bool:
    class_name = type(engine).__name__.lower()
    module_name = type(engine).__module__.lower()
    provider_name = str(getattr(engine, "provider_name", "")).lower()
    return (
        class_name.startswith("mock")
        or module_name.endswith(("mock_llm", "mock_tts"))
        or provider_name == "mock"
    )


def _unwrap_tracing_proxy(
    engine: object, proxy_type: type | tuple[type, ...]
) -> tuple[object, bool]:
    current = engine
    proxied = False
    seen: set[int] = set()
    while isinstance(current, proxy_type):
        identity = id(current)
        if identity in seen:
            break
        seen.add(identity)
        proxied = True
        current = object.__getattribute__(current, "_target")
    return current, proxied


def _runtime_engine_evidence(
    config: Any,
    engines: Mapping[str, object] | None,
    scope: Literal["runtime", "static"],
) -> tuple[bool, str, dict[str, Any]]:
    if scope == "static":
        return True, "not_required_for_static_scope", {"provided": engines is not None}
    if engines is None:
        return False, "runtime_engines_missing", {"missing": ["llm", "tts"]}

    missing = [name for name in ("llm", "tts") if engines.get(name) is None]
    if missing:
        code = (
            "runtime_engines_missing"
            if len(missing) == 2
            else f"runtime_{missing[0]}_missing"
        )
        return False, code, {"missing": missing}

    try:
        from animetta.observability.service_proxy import InstrumentedServiceProxy
        from animetta.services.llm.openai_llm import OpenAILLM
        from animetta.services.tts.qwen3_tts import Qwen3TTSTTS
        from animetta.tracing.proxy import TracingProxy
    except ImportError as exc:
        return False, "runtime_engine_types_unavailable", {"reason": str(exc)}

    proxy_types = (TracingProxy, InstrumentedServiceProxy)
    llm, llm_proxied = _unwrap_tracing_proxy(engines["llm"], proxy_types)
    tts, tts_proxied = _unwrap_tracing_proxy(engines["tts"], proxy_types)
    unwrapped = {"llm": llm, "tts": tts}
    unexpected = [
        f"{name}:{type(engine).__name__}"
        for name, engine in unwrapped.items()
        if _is_mock_engine(engine)
    ]
    if unexpected:
        return False, "mock_engines_detected", {"unexpected": unexpected}

    issues: list[dict[str, Any]] = []

    def issue(engine: str, code: str, **detail: Any) -> None:
        issues.append({"engine": engine, "code": code, **detail})

    if not isinstance(llm, OpenAILLM):
        issue(
            "llm",
            "runtime_llm_type_mismatch",
            expected="OpenAILLM",
            actual=type(llm).__name__,
        )
    else:
        llm_model = getattr(llm, "model", None)
        if llm_model != "deepseek-v4-flash":
            issue(
                "llm",
                "runtime_llm_model_mismatch",
                expected="deepseek-v4-flash",
                actual=llm_model,
            )
        base_url = str(getattr(llm, "base_url", "") or "")
        hostname = (urlparse(base_url).hostname or "").lower()
        provider = llm._get_provider_name()
        if (
            provider != "deepseek"
            or not hostname.endswith("deepseek.com")
            or base_url.rstrip("/") != GOLDEN_DEEPSEEK_BASE_URL.rstrip("/")
        ):
            issue(
                "llm",
                "runtime_llm_provider_mismatch",
                expected_provider="deepseek",
                provider=provider,
                base_url=_safe_url_for_diagnostic(base_url),
                base_url_matches=False,
            )
        thinking = getattr(llm, "extra_body", {}).get("thinking", {}).get("type")
        if thinking != "disabled":
            issue(
                "llm",
                "runtime_llm_thinking_mismatch",
                expected="disabled",
                actual=thinking,
            )
        if not _present(getattr(llm, "api_key", None)):
            issue("llm", "runtime_llm_credentials_missing", present=False)

    if not isinstance(tts, Qwen3TTSTTS):
        issue(
            "tts",
            "runtime_tts_type_mismatch",
            expected="Qwen3TTSTTS",
            actual=type(tts).__name__,
        )
    else:
        tts_model = getattr(tts, "model", None)
        if tts_model != GOLDEN_QWEN_MODEL_ID:
            issue(
                "tts",
                "runtime_tts_model_mismatch",
                expected=GOLDEN_QWEN_MODEL_ID,
                actual=tts_model,
            )
        speaker = getattr(tts, "speaker", None)
        if speaker != "custom":
            issue(
                "tts",
                "runtime_tts_speaker_mismatch",
                expected="custom",
                actual=speaker,
            )
        configured_ref_audio = getattr(getattr(config, "tts", None), "ref_audio_path", None)
        configured_ref_text = getattr(getattr(config, "tts", None), "ref_text", None)
        runtime_ref_audio = getattr(tts, "ref_audio_path", None)
        runtime_ref_text = getattr(tts, "ref_text", None)
        runtime_icl_ok = (
            getattr(tts, "x_vector_only", None) is False
            and _present(runtime_ref_text)
            and runtime_ref_text == configured_ref_text
            and _present(runtime_ref_audio)
            and runtime_ref_audio == configured_ref_audio
        )
        if not runtime_icl_ok:
            issue(
                "tts",
                "runtime_tts_icl_mismatch",
                x_vector_only=getattr(tts, "x_vector_only", None),
                transcript_present=_present(runtime_ref_text),
                transcript_matches=runtime_ref_text == configured_ref_text,
                reference_audio_matches=runtime_ref_audio == configured_ref_audio,
            )

    proxied = [
        name
        for name, was_proxied in (("llm", llm_proxied), ("tts", tts_proxied))
        if was_proxied
    ]
    if issues:
        code = issues[0]["code"] if len(issues) == 1 else "runtime_engine_identity_mismatch"
        return False, code, {"issues": issues, "proxied": proxied}
    return True, "ok", {
        "provided": True,
        "classes": {"llm": type(llm).__name__, "tts": type(tts).__name__},
        "proxied": proxied,
    }


def _probe(probe: Callable[..., Mapping[str, Any]], *args: str) -> dict[str, Any]:
    try:
        return dict(probe(*args))
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def run_golden_preflight(
    config: Any,
    context: GoldenPreflightContext | None = None,
) -> GoldenPreflightReport:
    """Evaluate every golden invariant locally and return all failures at once."""
    ctx = context or GoldenPreflightContext()
    project_root = Path(ctx.project_root)
    secrets = _secret_values(config, ctx.env)
    checks: list[GoldenPreflightCheck] = []

    def add(name: str, ok: bool, code: str, detail: Mapping[str, Any]) -> None:
        checks.append(
            GoldenPreflightCheck(
                name=name,
                ok=ok,
                code=code,
                detail=_sanitize(dict(detail), secrets),
            )
        )

    runtime_profile = _attribute(config, "system", "runtime_profile")
    add(
        "effective_profile",
        runtime_profile == "golden",
        "ok" if runtime_profile == "golden" else "profile_not_golden",
        {"runtime_profile": runtime_profile},
    )

    persona = getattr(config, "persona", None)
    add(
        "persona",
        persona == "anima.v0.1",
        "ok" if persona == "anima.v0.1" else "persona_mismatch",
        {"persona": persona},
    )

    local_llm = _attribute(config, "services", "local_llm")
    local_llm_ok = local_llm is None
    add(
        "aux_local_llm",
        local_llm_ok,
        "ok" if local_llm_ok else "local_llm_enabled",
        {"selected": local_llm},
    )

    long_term_memory_mode = _attribute(config, "system", "long_term_memory_mode")
    long_term_memory_ok = long_term_memory_mode == "off"
    add(
        "aux_long_term_memory",
        long_term_memory_ok,
        "ok" if long_term_memory_ok else "long_term_memory_enabled",
        {"mode": long_term_memory_mode},
    )

    enable_tools = _attribute(config, "system", "enable_tools")
    tools_ok = enable_tools is False
    add(
        "aux_tools",
        tools_ok,
        "ok" if tools_ok else "tools_enabled",
        {"enabled": enable_tools},
    )

    enable_subtitle_translation = _attribute(
        config,
        "system",
        "enable_subtitle_translation",
    )
    subtitle_translation_ok = enable_subtitle_translation is False
    add(
        "aux_subtitle_translation",
        subtitle_translation_ok,
        "ok" if subtitle_translation_ok else "subtitle_translation_enabled",
        {"enabled": enable_subtitle_translation},
    )

    enable_active_memes = _attribute(config, "system", "enable_active_memes")
    active_memes_ok = enable_active_memes is False
    add(
        "aux_active_memes",
        active_memes_ok,
        "ok" if active_memes_ok else "active_memes_enabled",
        {"enabled": enable_active_memes},
    )

    humor_enabled = _attribute(config, "humor", "enabled")
    humor_ok = humor_enabled is False
    add(
        "aux_humor",
        humor_ok,
        "ok" if humor_ok else "humor_enabled",
        {"enabled": humor_enabled},
    )

    llm_selection = _attribute(config, "services", "agent")
    llm_config = _attribute(config, "agent", "llm_config")
    llm_type = getattr(llm_config, "type", None)
    llm_provider_ok = llm_selection == "deepseek" and llm_type == "deepseek"
    add(
        "llm_provider",
        llm_provider_ok,
        "ok" if llm_provider_ok else "llm_provider_mismatch",
        {"selected": llm_selection, "config_type": llm_type},
    )

    llm_model = getattr(llm_config, "model", None)
    llm_model_ok = llm_model == "deepseek-v4-flash"
    add(
        "llm_model",
        llm_model_ok,
        "ok" if llm_model_ok else "llm_model_mismatch",
        {"model": llm_model},
    )

    thinking = getattr(llm_config, "thinking", None)
    thinking_ok = thinking == "disabled"
    add(
        "llm_thinking",
        thinking_ok,
        "ok" if thinking_ok else "thinking_enabled",
        {"thinking": thinking},
    )

    configured_key = getattr(llm_config, "api_key", None)
    credential_source = "config" if _present(configured_key) else None
    if credential_source is None:
        for env_name in ("DEEPSEEK_API_KEY", "LLM_API_KEY"):
            if _present(ctx.env.get(env_name)):
                credential_source = env_name
                break
    credential_ok = credential_source is not None
    add(
        "credentials",
        credential_ok,
        "ok" if credential_ok else "missing_credentials",
        {"present": credential_ok, "source": credential_source},
    )

    tts_selection = _attribute(config, "services", "tts")
    tts_config = getattr(config, "tts", None)
    tts_type = getattr(tts_config, "type", None)
    tts_provider_ok = tts_selection == "alice_vc" and tts_type == "qwen3"
    add(
        "tts_provider",
        tts_provider_ok,
        "ok" if tts_provider_ok else "tts_provider_mismatch",
        {"selected": tts_selection, "config_type": tts_type},
    )

    tts_model = getattr(tts_config, "model", None)
    tts_model_ok = tts_model == GOLDEN_QWEN_MODEL_ID
    add(
        "tts_model",
        tts_model_ok,
        "ok" if tts_model_ok else "tts_model_not_stable",
        {"model": tts_model},
    )

    transcript_present = _present(getattr(tts_config, "ref_text", None))
    x_vector_only = getattr(tts_config, "x_vector_only", None)
    if x_vector_only is not False:
        alice_icl_ok = False
        alice_icl_code = "alice_icl_disabled"
    elif not transcript_present:
        alice_icl_ok = False
        alice_icl_code = "reference_transcript_missing"
    else:
        alice_icl_ok = True
        alice_icl_code = "ok"
    add(
        "alice_icl",
        alice_icl_ok,
        alice_icl_code,
        {"x_vector_only": x_vector_only, "transcript_present": transcript_present},
    )

    ref_audio = _resolve_project_path(
        project_root,
        getattr(tts_config, "ref_audio_path", None),
    )
    audio_ok, audio_code, audio_detail = _reference_audio_evidence(ref_audio)
    add("alice_reference_audio", audio_ok, audio_code, audio_detail)

    cuda_evidence = _probe(ctx.cuda_probe)
    cuda_ok = cuda_evidence.get("available") is True
    cuda_detail = {key: value for key, value in cuda_evidence.items() if key != "available"}
    add("cuda", cuda_ok, "ok" if cuda_ok else "cuda_unavailable", cuda_detail)

    dependency_evidence = _probe(ctx.dependency_probe, "qwen_tts")
    dependency_ok = dependency_evidence.get("available") is True
    dependency_detail = {
        key: value for key, value in dependency_evidence.items() if key != "available"
    }
    add(
        "qwen_tts_dependency",
        dependency_ok,
        "ok" if dependency_ok else "qwen_tts_missing",
        dependency_detail,
    )

    cache_ok, cache_code, cache_detail, model_revision = _model_cache_evidence(
        GOLDEN_QWEN_MODEL_ID,
        ctx.env,
    )
    add("qwen_model_cache", cache_ok, cache_code, cache_detail)

    live2d_config_code: str | None = None
    live2d_config_detail: dict[str, Any] = {}
    if ctx.live2d_model_path is not None:
        live2d_model_path = ctx.live2d_model_path
    else:
        (
            live2d_model_path,
            live2d_config_code,
            live2d_config_detail,
        ) = _configured_live2d_path(project_root)
    if live2d_config_code:
        live2d_ok = False
        live2d_code = live2d_config_code
        live2d_detail = live2d_config_detail
    else:
        live2d_asset = _resolve_live2d_asset(project_root, live2d_model_path)
        live2d_ok, live2d_code, live2d_detail = _live2d_asset_evidence(
            live2d_asset,
            live2d_model_path,
            next(
                (
                    root
                    for root in _live2d_asset_roots(project_root)
                    if live2d_asset is not None and live2d_asset.is_relative_to(root)
                ),
                _live2d_asset_roots(project_root)[0],
            ),
        )
    add(
        "live2d_asset",
        live2d_ok,
        live2d_code,
        live2d_detail,
    )

    frontend_index = project_root / "frontend" / "dist" / "index.html"
    frontend_ok, frontend_code, frontend_detail = _frontend_dist_evidence(frontend_index)
    add(
        "frontend_dist",
        frontend_ok,
        frontend_code,
        frontend_detail,
    )

    runtime_engines_ok, runtime_engines_code, runtime_engines_detail = (
        _runtime_engine_evidence(config, ctx.runtime_engines, ctx.scope)
    )
    add(
        "runtime_engines",
        runtime_engines_ok,
        runtime_engines_code,
        runtime_engines_detail,
    )

    metadata = _sanitize(
        {
            "runtime_profile": runtime_profile,
            "scope": ctx.scope,
            "persona": persona,
            "auxiliary": {
                "local_llm_disabled": local_llm_ok,
                "long_term_memory_off": long_term_memory_ok,
                "tools_disabled": tools_ok,
                "subtitle_translation_disabled": subtitle_translation_ok,
                "active_memes_disabled": active_memes_ok,
                "humor_disabled": humor_ok,
            },
            "llm": {
                "provider": llm_selection,
                "model": llm_model,
                "thinking": thinking,
                "credential_present": credential_ok,
            },
            "tts": {
                "provider": tts_selection,
                "model": tts_model,
                "speaker": getattr(tts_config, "speaker", None),
                "x_vector_only": x_vector_only,
                "model_revision": model_revision,
            },
            "gpu": cuda_detail,
            "assets": {
                "alice_reference_audio": audio_ok,
                "live2d": live2d_ok,
                "frontend": frontend_ok,
            },
        },
        secrets,
    )
    report_ok = all(check.ok for check in checks)
    return GoldenPreflightReport(
        ok=report_ok,
        scope=ctx.scope,
        acceptance_ready=ctx.scope == "runtime" and report_ok,
        checks=tuple(checks),
        metadata=metadata,
    )

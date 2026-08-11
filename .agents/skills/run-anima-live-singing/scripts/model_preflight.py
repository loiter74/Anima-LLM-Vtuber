"""Read-only preflight for the configured Animetta singing voice."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

RVC_MODULES = (
    "ffmpeg",
    "faiss",
    "librosa",
    "parselmouth",
    "pyworld",
    "torchcrepe",
    "transformers",
)
SEPARATION_MODULES = ("demucs", "numpy", "soundfile", "torch", "torchaudio")


def _external_modules(python_exe: str, names: tuple[str, ...] = RVC_MODULES) -> dict[str, bool]:
    code = (
        "import importlib.util,json; names="
        + repr(names)
        + "; print(json.dumps({name: bool(importlib.util.find_spec(name)) for name in names}))"
    )
    try:
        result = subprocess.run(
            [python_exe, "-c", code],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {name: False for name in names}
    if result.returncode != 0:
        return {name: False for name in names}
    return {name: bool(value) for name, value in json.loads(result.stdout).items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--require-voice", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path[:0] = [str(repo_root), str(repo_root / "src")]
    load_dotenv(repo_root / ".env", override=False)
    logger.remove()

    from animetta.config.singing import SingingConfig
    from animetta.host_rvc_contract import HOST_RVC_CONTRACT
    from animetta.services.singing.rvc_bridge import RVCBridge
    from scripts.rvc_preflight import HOST_RVC_EXPECTED_IDENTITY, run_preflight

    raw = yaml.safe_load((repo_root / "config" / "singing.yaml").read_text(encoding="utf-8"))
    config = SingingConfig(**raw["singing"])
    api_key = os.getenv(config.rvc.api_key_env, "")
    host_base_url = os.getenv("RVC_HOST_URL", "http://127.0.0.1:8769")
    bridge = RVCBridge(
        rvc_path=config.rvc.rvc_path,
        python_exe=config.rvc.python_exe,
        model_name=config.rvc.model_name,
        index_path=config.rvc.index_path,
        f0_method=config.rvc.f0_method,
        base_url=host_base_url,
        api_key=api_key,
        expected_revision=config.rvc.expected_revision,
        request_timeout_seconds=config.rvc.request_timeout_seconds,
    )

    runtime_assets = {
        "python": HOST_RVC_CONTRACT.python_executable,
        "voice_model": HOST_RVC_CONTRACT.runtime_root
        / "assets"
        / "weights"
        / HOST_RVC_CONTRACT.model,
        "hubert_config": HOST_RVC_CONTRACT.hubert_model_dir / "config.json",
        "hubert_model": HOST_RVC_CONTRACT.hubert_model_dir / "pytorch_model.bin",
        "rmvpe_model": HOST_RVC_CONTRACT.runtime_root / "assets" / "rmvpe" / "rmvpe.pt",
        "separation_python": HOST_RVC_CONTRACT.separation_python_executable,
        "demucs_wrapper": repo_root / "scripts" / "demucs_fix.py",
    }
    problems = bridge.availability_problems()
    problems.extend(
        f"runtime asset missing: {name}"
        for name, path in runtime_assets.items()
        if not path.is_file()
    )
    modules = _external_modules(str(HOST_RVC_CONTRACT.python_executable))
    missing_modules = [name for name, available in modules.items() if not available]
    if missing_modules:
        problems.append("host python modules missing: " + ", ".join(missing_modules))
    separation_modules = _external_modules(
        str(HOST_RVC_CONTRACT.separation_python_executable), SEPARATION_MODULES
    )
    missing_separation_modules = [
        name for name, available in separation_modules.items() if not available
    ]
    if missing_separation_modules:
        problems.append("host separation modules missing: " + ", ".join(missing_separation_modules))
    if shutil.which("ffmpeg") is None:
        problems.append("ffmpeg CLI missing")

    host: dict[str, object]
    try:
        host = run_preflight(
            base_url=host_base_url,
            api_key=api_key,
            expected_identity=HOST_RVC_EXPECTED_IDENTITY,
        )
    except (OSError, RuntimeError, ValueError) as error:
        host = {
            "status": "failed",
            "category": getattr(error, "category", "unavailable"),
            "error": str(error),
        }
        problems.append(f"host preflight failed: {error}")

    index_path = Path(config.rvc.index_path)
    if config.rvc.index_path and not index_path.is_absolute():
        index_path = bridge.rvc_path / index_path
    evidence = {
        "rvc_enabled": config.rvc.enabled,
        "rvc_required": config.rvc.required,
        "voice_ready": config.rvc.enabled and not problems and host.get("status") == "passed",
        "host_url": host_base_url,
        "host": host,
        "identity": HOST_RVC_EXPECTED_IDENTITY,
        "rvc_path": str(bridge.rvc_path),
        "python_exe": str(HOST_RVC_CONTRACT.python_executable),
        "model_name": bridge.model_name,
        "model_path": str(bridge.model_path),
        "index_path": str(index_path) if config.rvc.index_path else "",
        "f0_method": bridge.f0_method,
        "python_modules": modules,
        "separation": {
            "primary": config.separation.engine,
            "fallback": config.separation.fallback_engine,
            "model": HOST_RVC_CONTRACT.separation_model,
            "python_exe": str(HOST_RVC_CONTRACT.separation_python_executable),
            "python_modules": separation_modules,
            "demucs_in_project_python": bool(importlib.util.find_spec("demucs")),
        },
        "problems": problems,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 1 if args.require_voice and not evidence["voice_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

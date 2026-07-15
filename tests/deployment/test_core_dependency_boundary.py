from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROHIBITED_PACKAGES = (
    "torch",
    "torchaudio",
    "qwen-tts",
    "faster-whisper",
    "funasr",
    "modelscope",
    "transformers",
    "peft",
    "accelerate",
    "sentence-transformers",
    "chromadb",
    "silero-vad",
)


def test_core_requirements_exclude_local_model_runtimes() -> None:
    core = "\n".join(
        line.split("#", 1)[0].strip().lower()
        for line in (ROOT / "requirements-core.txt").read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    )
    local = (ROOT / "requirements-local-ai.txt").read_text(encoding="utf-8").lower()

    assert "starlette" in core
    assert "fastapi" not in core
    for package in PROHIBITED_PACKAGES:
        assert package not in core
    assert "torch" in local
    assert "faster-whisper" in local
    assert "silero-vad" in local


def test_core_server_imports_when_local_model_packages_are_unavailable() -> None:
    script = r'''
import builtins
import sys

blocked = (
    "torch", "torchaudio", "qwen_tts", "faster_whisper", "silero_vad",
    "funasr", "modelscope", "transformers", "peft", "accelerate",
    "sentence_transformers", "chromadb",
)
original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and any(name == item or name.startswith(item + ".") for item in blocked):
        raise ModuleNotFoundError(f"blocked local-model dependency: {name}")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import animetta.core.socketio_server
import animetta.core.service_pool

loaded = set(sys.modules)
assert not any(name == item or name.startswith(item + ".") for item in blocked for name in loaded)
print("core-import-ok")
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "core-import-ok" in result.stdout

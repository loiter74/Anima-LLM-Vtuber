"""Configuration imports must not initialize runtime service implementations."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_app_config_import_does_not_load_services_or_torch() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from animetta.config import EffectiveConfig; "
                "assert EffectiveConfig.__name__ == 'EffectiveConfig'; "
                "assert 'animetta.services' not in sys.modules; "
                "assert 'torch' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        },
        text=True,
        timeout=30,
    )

    assert probe.returncode == 0, probe.stderr


def test_qwen_worker_import_does_not_require_llm_dependencies() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys

class BlockUnrelatedWorkerDependency:
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("langchain_core", "opentelemetry")
        if any(fullname == name or fullname.startswith(f"{name}.") for name in blocked):
            raise ModuleNotFoundError("blocked worker-only dependency", name=fullname)
        return None

sys.meta_path.insert(0, BlockUnrelatedWorkerDependency())
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS
assert Qwen3TTSTTS.__name__ == "Qwen3TTSTTS"
assert "animetta.services.llm" not in sys.modules
assert "animetta.tracing" not in sys.modules
""",
        ],
        check=False,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
        },
        text=True,
        timeout=30,
    )

    assert probe.returncode == 0, probe.stderr

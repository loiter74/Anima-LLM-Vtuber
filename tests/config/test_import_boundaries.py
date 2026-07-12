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
                "from animetta.config import AppConfig; "
                "assert AppConfig.__name__ == 'AppConfig'; "
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

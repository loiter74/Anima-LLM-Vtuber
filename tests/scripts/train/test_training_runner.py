from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.train.cli import _validate_gpu_evidence, run_step


def test_training_step_failure_stops_the_pipeline(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_step(
            "intentional failure",
            [sys.executable, "-c", "raise SystemExit(7)"],
            cwd=tmp_path,
        )

    assert error.value.returncode == 7


def test_gpu_evidence_must_be_recent_and_keep_required_headroom(tmp_path: Path) -> None:
    path = tmp_path / "gpu-probe.json"
    evidence = {
        "schema_version": 1,
        "run_id": "baseline-v001",
        "batch_size": 4,
        "gpu_name": "Test GPU",
        "memory_total_mib": 24_000,
        "memory_peak_used_mib": 15_000,
        "probe_command": ["python", "bounded_probe.py"],
        "competing_processes": [],
        "workspace_lifecycle_clear": True,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(evidence), encoding="utf-8")

    _validate_gpu_evidence(path, run_id="baseline-v001", batch_size=4)

    evidence["observed_at"] = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="最近 4 小时"):
        _validate_gpu_evidence(path, run_id="baseline-v001", batch_size=4)

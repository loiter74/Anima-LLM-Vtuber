from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.baseline_golden_path import run_baseline

NOW = datetime(2026, 7, 11, 12, 30, 45, tzinfo=UTC)


def _preflight(ok: bool = True) -> dict[str, Any]:
    return {"ok": ok, "scope": "static", "acceptance_ready": False, "checks": []}


def _http(status: int = 200, payload: dict[str, Any] | None = None):
    body = json.dumps(payload or {"status": "ok", "ready": True}).encode()
    return lambda _url, _timeout: (status, "application/json", body)


def test_success_writes_timestamped_atomic_json_evidence(tmp_path: Path) -> None:
    exit_code, evidence_path, report = run_baseline(
        config_path=Path("config/config.golden.yaml"),
        project_root=Path.cwd(),
        base_url="http://localhost",
        output_dir=tmp_path,
        preflight_runner=lambda *_: _preflight(),
        http_get=_http(),
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert report["ok"] is True
    assert evidence_path.name == "golden-baseline-20260711T123045Z.json"
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob("*.tmp"))


def test_readiness_503_fails_and_still_flushes_evidence(tmp_path: Path) -> None:
    def http_get(url: str, _timeout: float):
        if url.endswith("/ready"):
            return 503, "application/json", b'{"status":"not_ready"}'
        return 200, "application/json", b'{"status":"ok"}'

    exit_code, evidence_path, report = run_baseline(
        config_path=Path("golden.yaml"),
        project_root=Path.cwd(),
        base_url="http://localhost/",
        output_dir=tmp_path,
        preflight_runner=lambda *_: _preflight(),
        http_get=http_get,
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert evidence_path.is_file()
    assert report["checks"]["readiness"]["ok"] is False
    assert report["checks"]["readiness"]["status_code"] == 503


def test_html_200_is_not_accepted_as_health_json(tmp_path: Path) -> None:
    exit_code, _, report = run_baseline(
        config_path=Path("golden.yaml"),
        project_root=Path.cwd(),
        base_url="http://localhost",
        output_dir=tmp_path,
        preflight_runner=lambda *_: _preflight(),
        http_get=lambda *_: (200, "text/html", b"<html>SPA</html>"),
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert report["checks"]["liveness"]["code"] == "non_json_response"


def test_probe_exception_is_sanitized_and_evidence_is_written(tmp_path: Path) -> None:
    secret = "sk-super-secret"

    def explode(*_args):
        raise TimeoutError(f"timed out with Bearer {secret}")

    exit_code, evidence_path, report = run_baseline(
        config_path=Path("golden.yaml"),
        project_root=Path.cwd(),
        base_url=f"https://user:{secret}@localhost",
        output_dir=tmp_path,
        preflight_runner=explode,
        http_get=explode,
        now=lambda: NOW,
    )

    serialized = evidence_path.read_text(encoding="utf-8")
    assert exit_code == 1
    assert secret not in serialized
    assert "user:" not in serialized
    assert report["checks"]["preflight"]["code"] == "preflight_exception"


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    exit_code, _, report = run_baseline(
        config_path=Path("golden.yaml"),
        project_root=Path.cwd(),
        base_url="http://localhost",
        output_dir=tmp_path,
        preflight_runner=lambda *_: _preflight(),
        http_get=lambda *_: (200, "application/json", b"not-json"),
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert report["checks"]["liveness"]["code"] == "malformed_json"


def test_non_object_json_fails_closed_and_flushes_evidence(tmp_path: Path) -> None:
    exit_code, evidence_path, report = run_baseline(
        config_path=Path("golden.yaml"),
        project_root=Path.cwd(),
        base_url="http://localhost",
        output_dir=tmp_path,
        preflight_runner=lambda *_: _preflight(),
        http_get=lambda *_: (200, "application/json", b"[]"),
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert evidence_path.is_file()
    assert report["checks"]["liveness"]["code"] == "invalid_json_shape"

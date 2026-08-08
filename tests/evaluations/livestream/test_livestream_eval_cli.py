from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from evaluations.livestream import cli


def test_cli_module_executes_main_when_invoked_with_dash_m() -> None:
    env = os.environ.copy()
    source_root = Path(__file__).parents[3] / "src"
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(source_root), env.get("PYTHONPATH")) if value
    )
    completed = subprocess.run(
        [sys.executable, "-m", "evaluations.livestream.cli", "--help"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert completed.returncode == 0
    assert "usage: livestream-eval" in completed.stdout


def test_parser_exposes_all_six_commands_and_safe_defaults() -> None:
    parser = cli.build_parser()

    capture = parser.parse_args(
        ["capture", "--room-id", "123", "--tier", "low", "--dataset-id", "low-a"],
    )
    replay = parser.parse_args(["replay", "--dataset", "data/example"])
    clean = parser.parse_args(["clean", "--dataset", "data/example"])
    report = parser.parse_args(["report", "--run-dir", "artifacts/example"])
    demo = parser.parse_args(["demo"])

    assert capture.command == "capture"
    assert capture.platform == "bilibili-live"
    assert capture.duration_minutes == 120
    assert capture.observe_minutes == 15
    assert replay.command == "replay"
    assert replay.mode == "transport"
    assert replay.speed is None
    assert replay.duration_minutes is None
    assert clean.profile == "balanced"
    assert clean.target_language == "zh-CN"
    assert clean.synthetic_ratio == 0.10
    assert clean.seed == 20260717
    assert clean.llm_profile == "production"
    assert clean.derive_medium is False
    assert clean.medium_rate == 40
    assert report.safety_assessment is None
    assert demo.judge is False
    assert set(parser._subparsers._group_actions[0].choices) == {
        "capture",
        "clean",
        "validate",
        "replay",
        "report",
        "demo",
    }


def test_capture_parser_supports_anonymous_twitch_vod_windows() -> None:
    args = cli.build_parser().parse_args(
        [
            "capture",
            "--platform",
            "twitch-vod",
            "--vod-id",
            "source-secret",
            "--start-minutes",
            "87",
            "--tier",
            "high",
            "--dataset-id",
            "high-candidate",
        ],
    )

    assert args.room_id is None
    assert args.vod_id == "source-secret"
    assert args.start_minutes == 87
    assert args.rate_cap_per_minute is None

    shaped = cli.build_parser().parse_args(
        [
            "capture",
            "--platform",
            "twitch-vod",
            "--vod-id",
            "source-secret",
            "--rate-cap-per-minute",
            "280",
            "--tier",
            "high",
            "--dataset-id",
            "high-shaped",
        ],
    )
    assert shaped.rate_cap_per_minute == 280
    assert shaped.deterministic_prefilter is False

    prefiltered = cli.build_parser().parse_args(
        [
            "capture",
            "--platform",
            "twitch-vod",
            "--vod-id",
            "source-secret",
            "--deterministic-prefilter",
            "--tier",
            "high",
            "--dataset-id",
            "high-prefiltered",
        ],
    )
    assert prefiltered.deterministic_prefilter is True


def test_cli_dispatches_capture_validate_replay_and_report(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        cli, "capture_dataset", lambda args: calls.append(("capture", args.room_id))
    )
    monkeypatch.setattr(
        cli, "validate_dataset", lambda args: calls.append(("validate", args.dataset))
    )
    monkeypatch.setattr(cli, "replay_dataset", lambda args: calls.append(("replay", args.mode)))
    monkeypatch.setattr(cli, "report_run", lambda args: calls.append(("report", args.run_dir)))
    monkeypatch.setattr(cli, "clean_dataset", lambda args: calls.append(("clean", args.dataset)))

    assert (
        cli.main(
            [
                "capture",
                "--room-id",
                "123",
                "--tier",
                "low",
                "--dataset-id",
                "low-a",
            ],
        )
        == 0
    )
    assert cli.main(["validate", "--dataset", str(tmp_path)]) == 0
    assert cli.main(["replay", "--dataset", str(tmp_path)]) == 0
    assert cli.main(["report", "--run-dir", str(tmp_path)]) == 0
    assert cli.main(["clean", "--dataset", str(tmp_path)]) == 0

    assert [name for name, _value in calls] == ["capture", "validate", "replay", "report", "clean"]


def test_full_replay_defaults_to_the_socketio_production_adapter() -> None:
    args = cli.build_parser().parse_args(
        ["replay", "--dataset", "data/example", "--mode", "full"],
    )

    assert args.processor is None
    assert args.server_url == "http://localhost"
    assert args.resource_container == "animetta"
    assert args.duration_minutes is None


def test_replay_duration_defaults_only_full_mode_to_ninety_minutes() -> None:
    assert cli._resolve_duration_seconds("transport", None) is None
    assert cli._resolve_duration_seconds("full", None) == 90 * 60
    assert cli._resolve_duration_seconds("full", 45) == 45 * 60

    with pytest.raises(ValueError, match="duration-minutes"):
        cli._resolve_duration_seconds("full", 0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("512KiB", 0.5), ("42MiB", 42.0), ("1.5GiB", 1536.0)],
)
def test_docker_resource_units_are_normalized_to_megabytes(
    value: str,
    expected: float,
) -> None:
    assert cli._parse_memory_megabytes(value) == expected


def test_safety_assessment_requires_explicit_assessed_nonnegative_counts(tmp_path: Path) -> None:
    assessment = tmp_path / "safety.json"
    assessment.write_text(
        json.dumps(
            {
                "status": "assessed",
                "severe_issues": 0,
                "privacy_leaks": 0,
                "misattributions": 0,
            }
        ),
        encoding="utf-8",
    )

    assert cli._load_safety_assessment(assessment)["status"] == "assessed"

    assessment.write_text('{"status":"unassessed"}', encoding="utf-8")
    with pytest.raises(ValueError, match="assessed JSON"):
        cli._load_safety_assessment(assessment)


def test_report_passes_post_run_safety_assessment_to_reporting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_write_report(run_dir: Path, **kwargs) -> dict[str, object]:
        captured["run_dir"] = run_dir
        captured.update(kwargs)
        return {"baseline_readiness": {"status": "pending"}}

    monkeypatch.setattr(cli, "write_report", fake_write_report)
    safety_path = tmp_path / "safety.json"
    args = cli.build_parser().parse_args(
        [
            "report",
            "--run-dir",
            str(tmp_path),
            "--safety-assessment",
            str(safety_path),
        ]
    )

    cli.report_run(args)

    assert captured["run_dir"] == tmp_path
    assert captured["safety_assessment_path"] == safety_path


def test_twitch_capture_failure_closes_writer_and_leaves_no_staging_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FailingCollector:
        def __init__(self, **_kwargs) -> None:
            pass

        def capture(self):
            raise RuntimeError("network failed")

    monkeypatch.setattr(cli, "TwitchVodCollector", FailingCollector)
    args = Namespace(
        platform="twitch-vod",
        vod_id="source-secret",
        room_id=None,
        start_minutes=0,
        tier="high",
        dataset_id="failed-capture",
        duration_minutes=120,
        observe_minutes=15,
        output_root=tmp_path,
        rate_cap_per_minute=300,
        deterministic_prefilter=True,
    )

    with pytest.raises(RuntimeError, match="network failed"):
        cli.capture_dataset(args)

    assert list(tmp_path.iterdir()) == []


def test_demo_runs_hermetic_and_produces_report(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    exit_code = cli.main(["demo", "--output", str(output)])

    assert exit_code == 0
    assert (output / "evidence.json").is_file()
    assert (output / "report.json").is_file()
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["conversation_rows"] >= 1
    assert "automated_judge" not in report


def test_demo_dispatches_to_run_demo(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "run_demo", lambda _args: calls.append("demo") or {})
    assert cli.main(["demo", "--output", str(tmp_path)]) == 0
    assert calls == ["demo"]


def test_demo_judge_is_explicit_opt_in() -> None:
    args = cli.build_parser().parse_args(["demo", "--judge"])

    assert args.judge is True


def test_judge_run_and_close_share_one_event_loop(monkeypatch, tmp_path: Path) -> None:
    from evaluations.livestream import judge as judge_module

    loop_ids: list[int] = []

    class FakeJudge:
        async def close(self) -> None:
            import asyncio

            loop_ids.append(id(asyncio.get_running_loop()))

    async def fake_run_judge(run_dir: Path, judge: FakeJudge):
        import asyncio

        assert run_dir == tmp_path
        loop_ids.append(id(asyncio.get_running_loop()))
        return object()

    monkeypatch.setattr(judge_module, "run_judge", fake_run_judge)

    import asyncio

    asyncio.run(cli._run_and_close_judge(tmp_path, FakeJudge()))

    assert len(loop_ids) == 2
    assert loop_ids[0] == loop_ids[1]

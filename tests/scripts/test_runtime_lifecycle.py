from __future__ import annotations

from pathlib import Path

from scripts import runtime_lifecycle


def test_animetta_up_requires_host_tts_before_build(monkeypatch) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    host_calls: list[bool] = []
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_tts_up",
        lambda *, best_effort: host_calls.append(best_effort),
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_up", lambda: None)

    monkeypatch.delenv("ANIMETTA_PROFILE", raising=False)
    runtime_lifecycle.run_operation("anima-up")

    assert host_calls == [False]
    assert commands[0][0][-1] == "scripts/qwen_preflight.py"
    assert commands[1][0][-1] == "scripts/rvc_preflight.py"
    production_environment = {"ANIMETTA_PROFILE": "production"}
    assert commands[2] == (
        ["docker", "compose", "build", "animetta"],
        production_environment,
    )
    assert commands[3] == (
        ["docker", "compose", "up", "-d", "--no-build", "animetta"],
        production_environment,
    )
    assert all("docker-compose.qwen.yml" not in command for command, _ in commands)


def test_animetta_up_preserves_an_explicit_runtime_profile(monkeypatch) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.setenv("ANIMETTA_PROFILE", "smoke")
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_up", lambda *, best_effort: None)
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_up", lambda: None)

    runtime_lifecycle.run_operation("anima-up")

    assert commands[2][1] == {"ANIMETTA_PROFILE": "smoke"}
    assert commands[3][1] == {"ANIMETTA_PROFILE": "smoke"}


def test_animetta_selftest_up_waits_for_qwen_and_uses_profile_environment(monkeypatch) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    host_calls: list[bool] = []
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_tts_up",
        lambda *, best_effort: host_calls.append(best_effort),
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_up", lambda: None)

    runtime_lifecycle.run_operation("anima-selftest-up")

    assert host_calls == [False]
    assert commands[0][0][-2:] == ["scripts/qwen_preflight.py", "--wait"]
    assert commands[1][0][-2:] == ["scripts/rvc_preflight.py", "--wait"]
    selftest_environment = {"ANIMETTA_PROFILE": "selftest"}
    assert commands[2] == (
        ["docker", "compose", "build", "animetta"],
        selftest_environment,
    )
    assert commands[3] == (
        ["docker", "compose", "up", "-d", "--no-build", "animetta"],
        selftest_environment,
    )
    assert all("--force-recreate" not in command for command, _ in commands)


def test_animetta_cleanup_is_scoped_and_non_destructive(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))

    runtime_lifecycle.run_operation("anima-down")

    assert commands == [["docker", "compose", "down", "--remove-orphans"]]
    assert all("--volumes" not in command and "--rmi" not in command for command in commands)


def test_host_tts_operations_are_explicit_and_anima_down_keeps_host_alive(
    monkeypatch,
) -> None:
    calls: list[str] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_tts_up",
        lambda *, best_effort: calls.append(f"up:{best_effort}"),
    )
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_tts_status",
        lambda: calls.append("status") or {"running": True, "ready": True},
    )
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_tts_stop",
        lambda: calls.append("stop"),
    )

    runtime_lifecycle.run_operation("host-tts-up")
    runtime_lifecycle.run_operation("host-tts-status")
    runtime_lifecycle.run_operation("host-tts-stop")
    runtime_lifecycle.run_operation("anima-down")

    assert calls == ["up:False", "status", "stop"]
    assert commands == [["docker", "compose", "down", "--remove-orphans"]]


def test_host_rvc_operations_are_explicit_and_anima_down_keeps_host_alive(
    monkeypatch,
) -> None:
    calls: list[str] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_up", lambda: calls.append("up"))
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_rvc_status",
        lambda: calls.append("status") or {"running": True, "ready": True},
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_stop", lambda: calls.append("stop"))

    runtime_lifecycle.run_operation("host-rvc-up")
    runtime_lifecycle.run_operation("host-rvc-status")
    runtime_lifecycle.run_operation("host-rvc-stop")
    runtime_lifecycle.run_operation("anima-down")

    assert calls == ["up", "status", "stop"]
    assert commands == [["docker", "compose", "down", "--remove-orphans"]]


def test_host_pid_file_rejects_invalid_or_non_positive_pid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "host-tts.pid"
    monkeypatch.setattr(runtime_lifecycle, "HOST_TTS_PID_FILE", pid_file)

    for contents in ("not-json", '{"pid": 0}', '{"pid": -1}', '{"pid": "7"}'):
        pid_file.write_text(contents, encoding="utf-8")
        assert runtime_lifecycle._read_host_pid() is None


def test_cross_platform_entrypoint_exists() -> None:
    assert (Path(__file__).parents[2] / "scripts" / "runtime_lifecycle.py").is_file()


def test_container_qwen_operations_are_not_public() -> None:
    assert not set(runtime_lifecycle.OPERATIONS) & {
        "qwen-build",
        "qwen-up",
        "qwen-deploy",
        "qwen-stop",
        "qwen-destroy",
    }

from __future__ import annotations

from pathlib import Path

import pytest

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
    production_environment = {
        "ANIMETTA_IMAGE": "animetta:local",
        "ANIMETTA_PROFILE": "production",
    }
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

    expected_environment = {
        "ANIMETTA_IMAGE": "animetta:local",
        "ANIMETTA_PROFILE": "smoke",
    }
    assert commands[2][1] == expected_environment
    assert commands[3][1] == expected_environment


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
    selftest_environment = {
        "ANIMETTA_IMAGE": "animetta:local",
        "ANIMETTA_PROFILE": "selftest",
    }
    assert commands[2] == (
        ["docker", "compose", "build", "animetta"],
        selftest_environment,
    )
    assert commands[3] == (
        ["docker", "compose", "up", "-d", "--no-build", "animetta"],
        selftest_environment,
    )
    assert all("--force-recreate" not in command for command, _ in commands)


def test_animetta_deploy_pulls_and_starts_the_selected_image_without_build(
    monkeypatch,
) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.delenv("ANIMETTA_PROFILE", raising=False)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_up", lambda *, best_effort: None)
    monkeypatch.setattr(runtime_lifecycle, "_host_rvc_up", lambda: None)
    image = "ghcr.io/loiter74/animetta:sha-" + "a" * 40

    runtime_lifecycle.run_operation("anima-deploy", image=image)

    deploy_environment = {
        "ANIMETTA_IMAGE": image,
        "ANIMETTA_PROFILE": "production",
    }
    assert commands[2:] == [
        (
            ["docker", "compose", "pull", "--include-deps", "animetta"],
            deploy_environment,
        ),
        (
            [
                "docker",
                "image",
                "inspect",
                image,
                "--format",
                "{{json .RepoDigests}}",
            ],
            deploy_environment,
        ),
        (
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            deploy_environment,
        ),
    ]
    assert all("build" not in command for command, _environment in commands[2:])


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/loiter74/animetta:main",
        "ghcr.io/loiter74/animetta:sha-" + "a" * 40,
        "ghcr.io/loiter74/animetta@sha256:" + "b" * 64,
    ],
)
def test_animetta_deploy_accepts_supported_image_references(image: str) -> None:
    assert runtime_lifecycle._validate_deploy_image(image) == image


@pytest.mark.parametrize(
    "image",
    [
        "animetta:local",
        "ghcr.io/other/animetta:main",
        "ghcr.io/loiter74/animetta:sha-short",
        "ghcr.io/loiter74/animetta:latest",
    ],
)
def test_animetta_deploy_rejects_untrusted_image_references(image: str) -> None:
    with pytest.raises(ValueError, match="image must be"):
        runtime_lifecycle.run_operation("anima-deploy", image=image)


def test_other_operations_reject_deploy_image_argument() -> None:
    with pytest.raises(ValueError, match="only valid with anima-deploy"):
        runtime_lifecycle.run_operation(
            "anima-up",
            image="ghcr.io/loiter74/animetta:main",
        )


def test_public_cli_requires_image_only_for_deploy() -> None:
    with pytest.raises(SystemExit):
        runtime_lifecycle.main(["anima-deploy"])

    with pytest.raises(SystemExit):
        runtime_lifecycle.main(
            [
                "anima-up",
                "--image",
                "ghcr.io/loiter74/animetta:main",
            ]
        )


def test_animetta_cleanup_is_scoped_and_non_destructive(monkeypatch) -> None:
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.delenv("ANIMETTA_PROFILE", raising=False)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )

    runtime_lifecycle.run_operation("anima-down")

    assert commands == [
        (
            ["docker", "compose", "down", "--remove-orphans"],
            {
                "ANIMETTA_IMAGE": "animetta:local",
                "ANIMETTA_PROFILE": "production",
            },
        )
    ]
    assert all(
        "--volumes" not in command and "--rmi" not in command for command, _environment in commands
    )


def test_host_tts_operations_are_explicit_and_anima_down_keeps_host_alive(
    monkeypatch,
) -> None:
    calls: list[str] = []
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.delenv("ANIMETTA_PROFILE", raising=False)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
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
    assert commands[0][0] == ["docker", "compose", "down", "--remove-orphans"]
    assert commands[0][1] == {
        "ANIMETTA_IMAGE": "animetta:local",
        "ANIMETTA_PROFILE": "production",
    }


def test_host_rvc_operations_are_explicit_and_anima_down_keeps_host_alive(
    monkeypatch,
) -> None:
    calls: list[str] = []
    commands: list[tuple[list[str], dict[str, str] | None]] = []
    monkeypatch.delenv("ANIMETTA_PROFILE", raising=False)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_run",
        lambda command, *, environment=None: commands.append((command, environment)),
    )
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
    assert commands[0][0] == ["docker", "compose", "down", "--remove-orphans"]
    assert commands[0][1] == {
        "ANIMETTA_IMAGE": "animetta:local",
        "ANIMETTA_PROFILE": "production",
    }


def test_host_pid_file_rejects_invalid_or_non_positive_pid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "host-tts.pid"
    monkeypatch.setattr(runtime_lifecycle, "HOST_TTS_PID_FILE", pid_file)

    for contents in ("not-json", '{"pid": 0}', '{"pid": -1}', '{"pid": "7"}'):
        pid_file.write_text(contents, encoding="utf-8")
        assert runtime_lifecycle._read_host_pid() is None


def test_host_tts_stop_waits_for_the_process_tree_to_exit(monkeypatch) -> None:
    commands: list[list[str]] = []
    process_states = iter([True, True, False])

    monkeypatch.setattr(runtime_lifecycle, "_read_host_pid", lambda: 123)
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_listener_pid", lambda: None)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_is_expected_host_process",
        lambda pid: next(process_states),
    )
    monkeypatch.setattr(
        runtime_lifecycle.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )
    monkeypatch.setattr(runtime_lifecycle.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(runtime_lifecycle, "_remove_host_pid_file", lambda: None)

    runtime_lifecycle._host_tts_stop()

    assert commands == [["taskkill", "/PID", "123", "/T", "/F"]]


def test_host_tts_stop_fails_when_the_process_tree_survives(monkeypatch) -> None:
    monkeypatch.setattr(runtime_lifecycle, "_read_host_pid", lambda: 123)
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_listener_pid", lambda: None)
    monkeypatch.setattr(runtime_lifecycle, "_is_expected_host_process", lambda _pid: True)
    monkeypatch.setattr(
        runtime_lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(runtime_lifecycle.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="Host TTS process tree did not stop"):
        runtime_lifecycle._host_tts_stop()


def test_host_tts_stop_uses_expected_listener_when_pid_file_is_stale(monkeypatch) -> None:
    terminated: list[int] = []

    monkeypatch.setattr(runtime_lifecycle, "_read_host_pid", lambda: 123)
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_listener_pid", lambda: 456)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_terminate_host_process",
        lambda pid: terminated.append(pid),
    )
    monkeypatch.setattr(runtime_lifecycle, "_remove_host_pid_file", lambda: None)

    runtime_lifecycle._host_tts_stop()

    assert set(terminated) == {123, 456}


def test_host_tts_status_uses_listener_when_pid_file_is_stale(monkeypatch) -> None:
    monkeypatch.setattr(runtime_lifecycle, "_read_host_pid", lambda: 123)
    monkeypatch.setattr(runtime_lifecycle, "_host_tts_listener_pid", lambda: 456)
    monkeypatch.setattr(
        runtime_lifecycle,
        "_is_expected_host_process",
        lambda pid: pid == 456,
    )
    monkeypatch.setattr(runtime_lifecycle, "_host_token", lambda: "secret")
    monkeypatch.setattr(
        runtime_lifecycle,
        "_host_request_json",
        lambda path, _token: (
            {"ready": True} if path == "/ready" else runtime_lifecycle.HOST_TTS_IDENTITY
        ),
    )

    assert runtime_lifecycle._host_tts_status() == {
        "running": True,
        "ready": True,
        "identity_matches": True,
    }


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

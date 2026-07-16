from __future__ import annotations

from pathlib import Path

from scripts import runtime_lifecycle


def test_qwen_up_never_builds_or_recreates(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))

    runtime_lifecycle.run_operation("qwen-up")

    assert commands[0] == [
        "docker",
        "compose",
        "-f",
        "docker-compose.qwen.yml",
        "up",
        "-d",
        "--no-build",
        "--no-recreate",
        "qwen-tts",
    ]
    assert commands[1][-2:] == ["scripts/qwen_preflight.py", "--wait"]
    assert all("build" not in command for command in commands)


def test_qwen_deploy_is_the_only_build_and_recreate_path(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(runtime_lifecycle, "_qwen_build_fingerprint", lambda: "fingerprint-1")

    runtime_lifecycle.run_operation("qwen-deploy")

    assert commands[0][-3:] == [
        "--build-arg",
        "QWEN_TTS_BUILD_FINGERPRINT=fingerprint-1",
        "qwen-tts",
    ]
    assert "--force-recreate" in commands[1]
    assert "--no-build" in commands[1]
    assert commands[2][-2:] == ["scripts/qwen_preflight.py", "--wait"]


def test_qwen_build_uses_quality_catalog_content_fingerprint(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))
    monkeypatch.setattr(runtime_lifecycle, "_qwen_build_fingerprint", lambda: "fingerprint-2")

    runtime_lifecycle.run_operation("qwen-build")

    assert commands == [
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.qwen.yml",
            "build",
            "--build-arg",
            "QWEN_TTS_BUILD_FINGERPRINT=fingerprint-2",
            "qwen-tts",
        ]
    ]


def test_animetta_up_preflights_before_build_and_never_manages_qwen(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))

    runtime_lifecycle.run_operation("anima-up")

    assert commands[0][-1] == "scripts/qwen_preflight.py"
    assert commands[1] == ["docker", "compose", "build", "animetta"]
    assert commands[2] == [
        "docker",
        "compose",
        "up",
        "-d",
        "--no-build",
        "animetta",
    ]
    assert all("docker-compose.qwen.yml" not in command for command in commands[1:])


def test_cleanup_operations_are_scoped_and_non_destructive(monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_lifecycle, "_run", lambda command: commands.append(command))

    runtime_lifecycle.run_operation("anima-down")
    runtime_lifecycle.run_operation("qwen-stop")
    runtime_lifecycle.run_operation("qwen-destroy")

    assert commands[0] == ["docker", "compose", "down", "--remove-orphans"]
    assert commands[1][-2:] == ["stop", "qwen-tts"]
    assert commands[2][-2:] == ["down", "--remove-orphans"]
    assert all("--volumes" not in command and "--rmi" not in command for command in commands)


def test_cross_platform_entrypoint_exists() -> None:
    assert (Path(__file__).parents[2] / "scripts" / "runtime_lifecycle.py").is_file()

"""Minecraft gameplay review harness contract tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from animetta.acceptance.minecraft_gameplay_review import (
    DEFAULT_VIEWER_WAIT_SECONDS,
    MinecraftGameplayReviewHarness,
    MinecraftReviewError,
    MinecraftReviewServerLease,
    create_review_app,
    resolve_external_runtime_dir,
)


def test_real_review_allows_a_bounded_manual_viewer_join_window() -> None:
    assert DEFAULT_VIEWER_WAIT_SECONDS == 10 * 60


class FakeBridge:
    def __init__(self, report: dict | None = None) -> None:
        self.callback = None
        self.start = AsyncMock(return_value=True)
        self.stop = AsyncMock()
        self.send_command = AsyncMock(
            return_value={
                "status": "success",
                "result": report
                or {
                    "completed": True,
                    "elapsed_seconds": 42.5,
                    "deaths": 0,
                    "phase_results": [
                        {
                            "phase": "iron_gear",
                            "success": True,
                            "actions_attempted": 4,
                            "actions_succeeded": 4,
                            "failure_category": None,
                            "failure_message": "",
                        }
                    ],
                    "final_inventory": {"iron_chestplate": 1},
                    "iron_gear_achieved": {
                        "iron_pickaxe": True,
                        "iron_sword": True,
                        "iron_helmet": True,
                        "iron_chestplate": True,
                        "iron_leggings": True,
                        "iron_boots": True,
                    },
                    "raw_error": "C:/secret/token",
                },
            }
        )

    def set_viewer_callback(self, callback) -> None:
        self.callback = callback


class FakeServer:
    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()


async def test_harness_requires_authenticated_confirmed_attachment_and_writes_safe_report(
    tmp_path: Path,
) -> None:
    bridge = FakeBridge()
    server = FakeServer()
    harness = MinecraftGameplayReviewHarness(
        token="review-token",
        artifact_dir=tmp_path,
        server=server,
        bridge=bridge,
        viewer_timeout_seconds=0.1,
    )

    await harness.prepare()
    assert bridge.callback is not None
    bridge.callback(
        "client_viewer_status",
        {
            "binding_state": "following",
            "confirmed": True,
            "username": "LUN077",
            "target": "AnimettaBot",
            "attempt": 2,
            "reason": "viewer_joined",
            "error": "C:/secret/token",
        },
    )
    result = await harness.run(authorization="Bearer review-token")

    assert result["binding"]["binding_state"] == "following"
    assert result["binding"]["confirmed"] is True
    assert result["report"]["completed"] is True
    assert result["report"]["iron_gear_complete"] is True
    bridge.send_command.assert_awaited_once_with(
        "survival_iron",
        {"timeout_ms": 35 * 60 * 1_000},
        timeout=35 * 60 + 30,
    )
    report_path = harness.artifact_path(result["gameplay_report"])
    assert report_path is not None
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "raw_error" not in payload
    assert "C:/secret" not in report_path.read_text(encoding="utf-8")

    await harness.close()
    await harness.close()
    bridge.stop.assert_awaited_once()
    server.stop.assert_awaited_once()


async def test_harness_rejects_bad_auth_and_unconfirmed_viewer(tmp_path: Path) -> None:
    harness = MinecraftGameplayReviewHarness(
        token="review-token",
        artifact_dir=tmp_path,
        server=FakeServer(),
        bridge=FakeBridge(),
        viewer_timeout_seconds=0.01,
    )
    await harness.prepare()

    with pytest.raises(MinecraftReviewError, match="authentication"):
        await harness.run(authorization="Bearer wrong")
    with pytest.raises(MinecraftReviewError, match="viewer_timeout"):
        await harness.run(authorization="Bearer review-token")

    await harness.close()


async def test_incomplete_run_exposes_only_bounded_material_counts(tmp_path: Path) -> None:
    bridge = FakeBridge(
        {
            "completed": False,
            "phase_results": [
                {
                    "phase": "wooden_pickaxe",
                    "success": False,
                    "failure_category": "action_failed",
                    "failure_code": "MISSING_MATERIALS",
                    "failure_item": "oak_planks",
                    "missing_count": 3,
                }
            ],
            "final_inventory": {
                "oak_log": 2,
                "oak_planks": 0,
                "stick": 8,
                "crafting_table": 1,
                "secret_item": 99,
            },
            "iron_gear_achieved": {},
        }
    )
    harness = MinecraftGameplayReviewHarness(
        token="review-token",
        artifact_dir=tmp_path,
        server=FakeServer(),
        bridge=bridge,
        viewer_timeout_seconds=0.1,
    )
    await harness.prepare()
    bridge.callback(
        "client_viewer_status",
        {
            "binding_state": "following",
            "confirmed": True,
            "username": "LUN077",
            "target": "AnimettaBot",
            "attempt": 1,
            "reason": "viewer_joined",
        },
    )

    with pytest.raises(MinecraftReviewError) as captured:
        await harness.run(authorization="Bearer review-token")

    assert captured.value.details["inventory_oak_log"] == "2"
    assert captured.value.details["inventory_oak_planks"] == "0"
    assert captured.value.details["inventory_stick"] == "8"
    assert captured.value.details["inventory_crafting_table"] == "1"
    assert "secret_item" not in captured.value.details
    await harness.close()


async def test_disposable_server_uses_isolated_project_port_and_world(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    async def run_command(args: list[str], env: dict[str, str]) -> None:
        calls.append((args, env))

    lease = MinecraftReviewServerLease(
        repository_dir=tmp_path,
        world_dir=tmp_path / "world",
        run_command=run_command,
        readiness_probe=AsyncMock(return_value=True),
    )

    await lease.start()
    ops = json.loads((tmp_path / "world" / "ops.json").read_text(encoding="utf-8"))
    assert ops == [
        {
            "uuid": "4a820eea-2c37-36b6-aa2b-1669cb1fbe12",
            "name": "AnimettaBot",
            "level": 4,
            "bypassesPlayerLimit": True,
        }
    ]
    await lease.stop()
    await lease.stop()

    assert calls[0][0][:4] == ["docker", "compose", "-p", "animetta-mc-review"]
    assert calls[0][0][-2:] == ["up", "-d"]
    assert calls[0][1]["ANIMETTA_MC_REVIEW_PORT"] == "25566"
    assert calls[0][1]["ANIMETTA_MC_REVIEW_WORLD_DIR"] == str((tmp_path / "world").resolve())
    assert calls[1][0][-4:] == [
        "-T",
        "minecraft",
        "rcon-cli",
        "gamerule spawnRadius 0",
    ]
    assert calls[2][0][-3:] == ["down", "--volumes", "--remove-orphans"]


async def test_disposable_server_allows_slow_cold_start_beyond_two_minutes(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    async def run_command(args: list[str], env: dict[str, str]) -> None:
        calls.append((args, env))

    readiness_probe = AsyncMock(side_effect=[False] * 60 + [True])
    sleep = AsyncMock()
    lease = MinecraftReviewServerLease(
        repository_dir=tmp_path,
        world_dir=tmp_path / "world",
        run_command=run_command,
        readiness_probe=readiness_probe,
        readiness_attempts=150,
        readiness_interval_seconds=2,
        sleep=sleep,
    )

    await lease.start()
    await lease.stop()

    assert readiness_probe.await_count == 61
    assert sleep.await_count == 60
    sleep.assert_awaited_with(2)
    assert calls[1][0][-4:] == [
        "-T",
        "minecraft",
        "rcon-cli",
        "gamerule spawnRadius 0",
    ]


async def test_disposable_server_seeds_verified_runtime_without_copying_world(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    (seed / "cache").mkdir(parents=True)
    (seed / "plugins").mkdir()
    (seed / "world").mkdir()
    (seed / "paper-1.21-130.jar").write_bytes(b"paper")
    (seed / "cache" / "mojang_1.21.jar").write_bytes(b"mojang")
    (seed / "plugins" / "spectatorplus-paper-1.2.1.jar").write_bytes(b"plugin")
    (seed / "world" / "level.dat").write_bytes(b"old-world")

    async def run_command(_args: list[str], _env: dict[str, str]) -> None:
        return None

    lease = MinecraftReviewServerLease(
        repository_dir=tmp_path,
        world_dir=tmp_path / "review-world",
        runtime_seed_dir=seed,
        run_command=run_command,
        readiness_probe=AsyncMock(return_value=True),
    )

    await lease.start()

    assert (lease.world_dir / "paper-1.21-130.jar").read_bytes() == b"paper"
    assert (lease.world_dir / "cache" / "mojang_1.21.jar").read_bytes() == b"mojang"
    assert (lease.world_dir / "plugins" / "spectatorplus-paper-1.2.1.jar").read_bytes() == b"plugin"
    assert not (lease.world_dir / "world").exists()
    await lease.stop()


async def test_loopback_app_authenticates_readiness_run_and_artifacts(tmp_path: Path) -> None:
    bridge = FakeBridge()
    harness = MinecraftGameplayReviewHarness(
        token="review-token",
        artifact_dir=tmp_path,
        server=FakeServer(),
        bridge=bridge,
        viewer_timeout_seconds=0.1,
    )
    app = create_review_app(harness)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.post("/ready")).status_code == 401
        ready = await client.post("/ready", headers={"authorization": "Bearer review-token"})
        assert ready.status_code == 200
        bridge.callback(
            "client_viewer_status",
            {
                "binding_state": "following",
                "confirmed": True,
                "username": "LUN077",
                "target": "AnimettaBot",
                "attempt": 1,
                "reason": "viewer_joined",
            },
        )
        run = await client.post("/v1/review/run", headers={"authorization": "Bearer review-token"})
        assert run.status_code == 202
        await asyncio.sleep(0)
        run = await client.get("/v1/review/run", headers={"authorization": "Bearer review-token"})
        assert run.status_code == 200
        report_url = run.json()["gameplay_report"]
        artifact = await client.get(report_url, headers={"authorization": "Bearer review-token"})
        assert artifact.status_code == 200
        assert artifact.json()["completed"] is True

    await harness.close()


def test_external_runtime_resolution_handles_git_worktrees(tmp_path: Path) -> None:
    canonical = tmp_path / "Anima"
    worktree = canonical / ".worktrees" / "minecraft-review"

    assert resolve_external_runtime_dir(worktree) == tmp_path / "voyager-mc-bot"
    assert resolve_external_runtime_dir(canonical) == tmp_path / "voyager-mc-bot"

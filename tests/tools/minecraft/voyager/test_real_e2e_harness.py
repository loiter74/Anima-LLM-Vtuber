"""Real acceptance harness is v2-only and uses isolated durable stores."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.voyager_real_e2e import load_config, start_bridge_with_retry


def test_harness_loads_isolated_v2_control_plane_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "tools.yaml"
    config_file.write_text(
        yaml.safe_dump({"minecraft": {"runtime": {"entrypoint": "src/index.js"}}}),
        encoding="utf-8",
    )

    config = load_config(config_file, tmp_path / "evidence")

    assert config.enabled is True
    assert config.journal_path.endswith("commands.db")
    assert config.skill_path.endswith("skills.db")
    assert not hasattr(config, "mode")
    assert not hasattr(config, "autonomous")


async def test_replacement_bridge_retries_after_server_releases_identity(tmp_path: Path) -> None:
    config_file = tmp_path / "tools.yaml"
    config_file.write_text("minecraft: {}\n", encoding="utf-8")
    config = load_config(config_file, tmp_path / "evidence")
    outcomes = iter((False, True))
    bridges = []
    delays = []

    class FakeBridge:
        def __init__(self, _config) -> None:
            self.stopped = False
            bridges.append(self)

        async def start(self) -> bool:
            return next(outcomes)

        async def stop(self) -> None:
            self.stopped = True

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    replacement = await start_bridge_with_retry(
        config,
        bridge_factory=FakeBridge,
        sleep=record_sleep,
    )

    assert replacement is bridges[1]
    assert bridges[0].stopped is True
    assert bridges[1].stopped is False
    assert delays == [2.0]

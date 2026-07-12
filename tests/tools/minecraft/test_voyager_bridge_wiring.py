"""Architecture guards for the Python-owned Voyager control plane."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from animetta.tools.minecraft.autonomous.loop import AutonomousLoop
from animetta.tools.minecraft.core import tools
from animetta.tools.minecraft.core.bridge import MinecraftBridge


def test_bridge_is_transport_only_and_has_no_voyager_mode_authority() -> None:
    source = inspect.getsource(MinecraftBridge)

    assert "self_evolution" not in source
    assert not hasattr(MinecraftBridge, "_launch_learning_loop")
    assert not hasattr(MinecraftBridge, "set_voyager_mode")


def test_legacy_autonomous_loop_has_no_voyager_mode_authority() -> None:
    source = inspect.getsource(AutonomousLoop)

    assert not hasattr(AutonomousLoop, "set_voyager_mode")
    assert "_voyager_mode" not in source


def test_init_bridge_never_starts_legacy_autonomous_owner() -> None:
    config = {
        "enabled": True,
        "mode": "learn",
        "bot": {"host": "localhost", "port": 25565, "username": "TestBot"},
    }
    tools._bridge = None
    try:
        with patch(
            "animetta.tools.minecraft.core.bridge.MinecraftBridge"
        ) as bridge_class:
            tools.init_bridge(config)

        assert bridge_class.call_args.kwargs["autonomous"] is False
    finally:
        tools._bridge = None


def test_legacy_constructor_arguments_do_not_create_competing_state() -> None:
    bridge = MinecraftBridge(
        MagicMock(),
        autonomous=True,
        service_pool=MagicMock(),
    )

    assert not hasattr(bridge, "_autonomous_loop")
    assert not hasattr(bridge, "_learning_task")
    assert not hasattr(bridge, "_voyager_mode")

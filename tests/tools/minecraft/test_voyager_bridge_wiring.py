"""Architecture guards for the Python-owned Voyager control plane."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.config import MinecraftConfig


def test_bridge_is_transport_only_and_has_no_voyager_mode_authority() -> None:
    source = inspect.getsource(MinecraftMcpBridge)

    assert "self_evolution" not in source
    assert not hasattr(MinecraftMcpBridge, "_launch_learning_loop")
    assert not hasattr(MinecraftMcpBridge, "set_voyager_mode")
    assert "create_subprocess_exec" not in inspect.getsource(MinecraftMcpBridge.start)


@pytest.mark.parametrize("field", ["mode", "autonomous"])
def test_removed_configuration_owner_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="Removed Minecraft config field"):
        MinecraftConfig.model_validate({field: "learn"})

"""Anima configuration cannot own viewer policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.core.config import MinecraftConfig


@pytest.mark.parametrize("field", ["viewer", "client_viewer"])
def test_viewer_configuration_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="moved to mc-mcp"):
        MinecraftConfig.model_validate({field: {"username": "Camera"}})

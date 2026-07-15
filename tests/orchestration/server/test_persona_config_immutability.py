from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.handlers.persona_handlers import PersonaHandlers


@pytest.mark.asyncio
async def test_socket_persona_switch_cannot_mutate_effective_config() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    active_config = MagicMock()
    base = MagicMock()
    base.global_config = active_config
    handler = PersonaHandlers(
        sio,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        base=base,
    )

    acknowledgement = await handler.on_set_persona("sid", {"persona_name": "alice"})

    assert base.global_config is active_config
    sio.emit.assert_awaited_once()
    event, payload = sio.emit.await_args.args[:2]
    assert event == "system:error"
    assert payload == {
        "type": "config_reload_required",
        "message": (
            "Update application.persona in config/animetta.yaml, then reload "
            "the canonical runtime configuration"
        ),
    }
    assert acknowledgement == {
        "ok": False,
        "type": "config_reload_required",
        "error": (
            "Update application.persona in config/animetta.yaml, then reload "
            "the canonical runtime configuration"
        ),
    }

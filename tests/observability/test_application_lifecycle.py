import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from animetta.config.manifest import EffectiveConfig, load_effective_config
from animetta.config.observability import ObservabilityConfig
from animetta.observability.ledger import SQLiteObservationLedger
from animetta.observability.mirrors import OTelMirror, PrometheusMirror
from animetta.observability.ports import (
    NoOpObservationQuery,
    NoOpObservationRecorder,
    NoOpObservationReportStore,
)
from animetta.orchestration.server.websocket import WebSocketServer


def _config(observability: dict | None = None) -> EffectiveConfig:
    with patch.dict(
        os.environ,
        {
            "ANIMETTA_PROFILE": "test",
            "ANIMETTA_HOST": "127.0.0.1",
            "ANIMETTA_PORT": "12394",
        },
        clear=True,
    ):
        config = load_effective_config("config/animetta.yaml", profile="test")
    if observability is None:
        return config
    application_payload = config.application.manifest_dict()
    application_payload["observability"] = observability
    application = type(config.application).model_validate(application_payload)
    return config.model_copy(update={"application": application})


def test_observability_config_defaults_local_on_and_otlp_off() -> None:
    config = ObservabilityConfig()

    assert config.enabled is True
    assert config.database_path == "data/observations.db"
    assert config.queue_capacity > 0
    assert config.drain_timeout_seconds > 0
    assert config.prometheus.enabled is True
    assert config.otlp.enabled is False
    assert config.privacy.development == "full"
    assert config.privacy.golden == "redacted"
    assert _config().observability == config


def _server(config):
    with (
        patch("socketio.AsyncServer") as sio,
        patch("socketio.ASGIApp"),
        patch("starlette.applications.Starlette"),
        patch("animetta.orchestration.server.websocket.ModelLoadingManager"),
    ):
        sio.return_value = MagicMock()
        return WebSocketServer(config)


def test_server_constructs_one_application_owned_ledger_and_injects_ports(tmp_path) -> None:
    config = _config({"database_path": str(tmp_path / "observations.db")})
    server = _server(config)

    assert isinstance(server.observation_ledger, SQLiteObservationLedger)
    assert server.observation_recorder is server.observation_ledger
    assert server.observation_query is server.observation_ledger
    assert server.observation_report_store is server.observation_ledger
    assert len(server.observation_mirrors) == 1
    assert isinstance(server.observation_mirrors[0], PrometheusMirror)
    assert server.session_manager.observation_recorder is server.observation_recorder

    with patch("animetta.orchestration.server.websocket.register_routes") as register:
        register.return_value = MagicMock()
        server.setup_routes()

    assert register.call_args.kwargs["observation_recorder"] is server.observation_recorder
    assert register.call_args.kwargs["observation_query"] is server.observation_query
    assert register.call_args.kwargs["observation_report_store"] is server.observation_report_store


def test_disabled_mode_installs_explicit_noop_ports() -> None:
    server = _server(_config({"enabled": False}))

    assert server.observation_ledger is None
    assert isinstance(server.observation_recorder, NoOpObservationRecorder)
    assert isinstance(server.observation_query, NoOpObservationQuery)
    assert isinstance(server.observation_report_store, NoOpObservationReportStore)
    assert server.cached_observation_health.enabled is False


def test_otlp_mirror_is_constructed_only_when_enabled(tmp_path) -> None:
    config = _config(
        {
            "database_path": str(tmp_path / "observations.db"),
            "prometheus": {"enabled": False},
            "otlp": {"enabled": True, "endpoint": "http://collector:4317"},
        }
    )
    mirror = MagicMock(spec=OTelMirror)
    with patch.object(OTelMirror, "from_endpoint", return_value=mirror) as factory:
        server = _server(config)

    factory.assert_called_once_with(
        "http://collector:4317",
        max_export_batch_size=512,
        schedule_delay_millis=5000,
    )
    assert server.observation_mirrors == [mirror]


async def test_missing_optional_otlp_exporter_degrades_health(tmp_path) -> None:
    config = _config(
        {
            "database_path": str(tmp_path / "observations.db"),
            "prometheus": {"enabled": False},
            "otlp": {"enabled": True},
        }
    )
    with patch.object(
        OTelMirror,
        "from_endpoint",
        side_effect=ModuleNotFoundError("OTLP exporter not installed"),
    ):
        server = _server(config)

    await server.observation_ledger.start()
    health = await server.observation_ledger.health()
    assert health.degraded is True
    assert "ModuleNotFoundError" in (health.last_error or "")
    await server.observation_ledger.close()


async def test_ledger_starts_before_other_runtime_work_and_closes_after_workers() -> None:
    server = _server(_config())
    order: list[str] = []
    server.observation_ledger = SimpleNamespace(
        start=AsyncMock(side_effect=lambda: order.append("ledger.start")),
        close=AsyncMock(side_effect=lambda: order.append("ledger.close")),
        health=AsyncMock(
            return_value=server.cached_observation_health,
        ),
    )
    server.session_manager.cleanup_all = AsyncMock(
        side_effect=lambda: order.append("sessions.stop")
    )
    server.memory_runtime.initialize = AsyncMock(side_effect=lambda: order.append("memory.start"))
    server.memory_runtime.shutdown = AsyncMock(side_effect=lambda: order.append("memory.stop"))

    with patch("animetta.orchestration.server.websocket.ServicePool") as pool:
        pool.init = AsyncMock(side_effect=lambda *args, **kwargs: order.append("pool.start"))
        pool.shutdown = AsyncMock(side_effect=lambda: order.append("pool.stop"))
        await server.prewarm_services()
        await server._cleanup_all_resources()

    assert order.index("ledger.start") < order.index("memory.start")
    assert order.index("sessions.stop") < order.index("ledger.close")
    assert order.index("memory.stop") < order.index("ledger.close")

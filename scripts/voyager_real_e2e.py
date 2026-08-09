"""Real GameBot v2 acceptance: cooperative stop and disconnect quarantine."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml

from animetta.tools.minecraft.core.assembly import assemble_control_plane
from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.config import MinecraftConfig
from animetta.tools.minecraft.voyager.command_models import (
    TERMINAL_COMMAND_STATES,
    ControllerState,
)
from animetta.tools.minecraft.voyager.gateway import ExecuteAtomicRequest, VoyagerGateway
from animetta.tools.minecraft.voyager.goal_models import AtomicAction
from animetta.tools.minecraft.voyager.journal import JournalCommand


async def start_bridge_with_retry(
    config: MinecraftConfig,
    *,
    attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    bridge_factory: Callable[[MinecraftConfig], MinecraftMcpBridge] = MinecraftMcpBridge,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> MinecraftMcpBridge:
    """Bound replacement login retries while the server releases the prior identity."""

    for attempt in range(attempts):
        bridge = bridge_factory(config)
        result = await bridge.start(profile=None, request_id=f"real-e2e-connect-{attempt}")
        if result.get("state") == "ready":
            return bridge
        await bridge.close()
        if attempt + 1 < attempts:
            await sleep(retry_delay_seconds * (attempt + 1))
    raise RuntimeError("replacement Minecraft bridge failed readiness")


async def wait_for_state(
    gateway: VoyagerGateway,
    command_id: str,
    *,
    timeout: float,
    running_ok: bool = False,
) -> JournalCommand:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        command = await gateway.status_command(
            caller_scope="system:real-e2e", command_id=command_id
        )
        if command.state in TERMINAL_COMMAND_STATES or (
            running_ok and command.state.value == "running"
        ):
            return command
        await asyncio.sleep(0.1)
    raise TimeoutError(f"command did not advance within {timeout}s: {command_id}")


async def run_real_acceptance(
    config: MinecraftConfig,
    *,
    deliberate_disconnect: bool,
) -> dict:
    bridge = MinecraftMcpBridge(config)
    started = await bridge.start(profile=None, request_id="real-e2e-connect")
    if started.get("state") != "ready":
        raise RuntimeError("Minecraft bridge failed readiness")
    plane = None
    try:
        plane = await assemble_control_plane(bridge, config)
        handle = await plane.gateway.execute(
            caller_scope="system:real-e2e",
            request=ExecuteAtomicRequest(
                contract_version="2",
                kind="atomic",
                request_id="real-e2e-action",
                action=AtomicAction(
                    capability="collect",
                    parameters={"block_type": "oak_log", "count": 64},
                ),
            ),
        )
        running = await wait_for_state(
            plane.gateway, handle.command_id, timeout=15, running_ok=True
        )
        if running.state in TERMINAL_COMMAND_STATES:
            raise RuntimeError("probe completed before its interruption point")

        if not deliberate_disconnect:
            stop = await plane.gateway.stop(
                caller_scope="system:real-e2e",
                request_id="real-e2e-stop",
                reason="cooperative acceptance stop",
            )
            terminal = await wait_for_state(plane.gateway, handle.command_id, timeout=30)
            stop_command = await plane.gateway.status_command(
                caller_scope="system:real-e2e", command_id=stop.stop_command_id
            )
            if stop.recovery_error is not None:
                raise RuntimeError(stop.recovery_error)
            if stop_command.state.value != "succeeded":
                raise RuntimeError(f"stop command did not complete: {stop_command.state.value}")
            if terminal.state.value not in {"cancelled", "cancelled_reconciled"}:
                raise RuntimeError(
                    f"cooperative stop did not cancel the active action: {terminal.state.value}"
                )
            return {
                "scenario": "cooperative_stop",
                "command_id": handle.command_id,
                "terminal_state": terminal.state.value,
                "stop_command_id": stop.stop_command_id,
                "stop_state": stop_command.state.value,
            }

        await bridge.disconnect_runtime(request_id="real-e2e-disconnect")
        terminal = await wait_for_state(plane.gateway, handle.command_id, timeout=30)
    finally:
        if plane is not None:
            await plane.close()
        await bridge.close()

    replacement = None
    recovered = None
    try:
        replacement = await start_bridge_with_retry(config)
        recovered = await assemble_control_plane(replacement, config)
        projection = await recovered.gateway.status(caller_scope="system:real-e2e")
        before_stop_state = recovered.controller.state.value
        stop = await recovered.gateway.stop(
            caller_scope="system:real-e2e",
            request_id="real-e2e-recovery-stop",
            reason="reconcile after deliberate disconnect",
        )
        evidence = {
            "scenario": "disconnect_recovery",
            "terminal_state": terminal.state.value,
            "controller_state_before_stop": before_stop_state,
            "controller_state_after_stop": recovered.controller.state.value,
            "status_readable": bool(projection.commands),
            "stop_command_id": stop.stop_command_id,
            "recovery_error": stop.recovery_error,
        }
        if terminal.state.value != "blocked_unknown":
            raise RuntimeError(f"disconnect did not quarantine outcome: {terminal.state.value}")
        if before_stop_state != ControllerState.QUARANTINED.value:
            raise RuntimeError("replacement controller did not preserve quarantine")
        if stop.recovery_error != "RECOVERY_INCOMPLETE":
            raise RuntimeError("replacement instance guessed an ambiguous outcome")
        if recovered.controller.state is not ControllerState.QUARANTINED:
            raise RuntimeError("incomplete recovery did not preserve quarantine")
        return evidence
    finally:
        if recovered is not None:
            await recovered.close()
        if replacement is not None:
            await replacement.shutdown_runtime(request_id="real-e2e-shutdown")
            await replacement.close()


def load_config(path: Path, artifact_dir: Path) -> MinecraftConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    minecraft = dict(payload.get("minecraft", {}))
    minecraft["enabled"] = True
    minecraft["journal_path"] = str(artifact_dir / "commands.db")
    minecraft["skill_path"] = str(artifact_dir / "skills.db")
    return MinecraftConfig.model_validate(minecraft)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config/tools.yaml"))
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--disconnect", action="store_true")
    args = parser.parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(
        run_real_acceptance(
            load_config(args.config, args.artifact_dir),
            deliberate_disconnect=args.disconnect,
        )
    )
    (args.artifact_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

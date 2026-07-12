"""Runtime-loss recovery that never awards interrupted task progress."""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts import ActionReceipt, GameBotObservation
from animetta.tools.gamebot.runtime import GameBotRuntime

from .contracts import VoyagerCheckpoint
from .repository import VoyagerRepository


class RecoveryState(StrEnum):
    RESUMED = "resumed"
    QUARANTINED = "quarantined"


class RecoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: RecoveryState
    reason: str = ""
    checkpoint: VoyagerCheckpoint | None = None
    fresh_observation: GameBotObservation | None = None
    invalid_receipt_hashes: tuple[str, ...] = ()
    unexplained_inventory: dict[str, int] = Field(default_factory=dict)


class RecoveryCoordinator:
    def __init__(self, *, runtime: GameBotRuntime, repository: VoyagerRepository) -> None:
        self._runtime = runtime
        self._repository = repository

    async def recover(
        self,
        *,
        session_id: str,
        interrupted_task_id: str,
        active_correlation_id: str,
        partial_receipts: list[ActionReceipt],
    ) -> RecoveryResult:
        del interrupted_task_id  # Never reused: the interrupted task is invalid by definition.
        invalid_hashes = tuple(receipt.content_hash for receipt in partial_receipts)

        try:
            await self._runtime.cancel_action(active_correlation_id)
        except Exception as exc:
            return RecoveryResult(
                state=RecoveryState.QUARANTINED,
                reason=f"cancellation_failed:{type(exc).__name__}",
                invalid_receipt_hashes=invalid_hashes,
            )

        health = await self._runtime.health()
        if not bool(health.get("healthy")):
            return RecoveryResult(
                state=RecoveryState.QUARANTINED,
                reason="runtime_unhealthy",
                invalid_receipt_hashes=invalid_hashes,
            )

        checkpoint = await self._repository.last_checkpoint(session_id)
        if checkpoint is None:
            return RecoveryResult(
                state=RecoveryState.QUARANTINED,
                reason="missing_committed_checkpoint",
                invalid_receipt_hashes=invalid_hashes,
            )

        fresh = await self._runtime.observe(f"recovery-{uuid4().hex}")
        checkpoint_inventory = checkpoint.metadata.get("inventory", {})
        unexplained = {
            item: count - int(checkpoint_inventory.get(item, 0))
            for item, count in fresh.inventory.items()
            if count > int(checkpoint_inventory.get(item, 0))
        }
        if unexplained:
            return RecoveryResult(
                state=RecoveryState.QUARANTINED,
                reason="unexplained_inventory_delta",
                checkpoint=checkpoint,
                fresh_observation=fresh,
                invalid_receipt_hashes=invalid_hashes,
                unexplained_inventory=unexplained,
            )

        return RecoveryResult(
            state=RecoveryState.RESUMED,
            checkpoint=checkpoint,
            fresh_observation=fresh,
            invalid_receipt_hashes=invalid_hashes,
        )

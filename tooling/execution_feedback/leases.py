from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .models import (
    CleanupStrategy,
    LeaseDecision,
    LeaseInspection,
    LeaseState,
    ResourceIdentity,
    ResourceLease,
    ResourceObservation,
    ResourceOwnership,
    validate_identifier,
)
from .store import IterationPlanStore


class ResourceInspector(Protocol):
    def inspect(self, identity: ResourceIdentity) -> ResourceObservation: ...


class ResourceTerminator(Protocol):
    def terminate(self, identity: ResourceIdentity, strategy: CleanupStrategy) -> bool: ...


def _same_identity(expected: ResourceIdentity, observed: ResourceIdentity) -> bool:
    return expected == observed


def _updated_lease(lease: ResourceLease, **updates: object) -> ResourceLease:
    payload = lease.model_dump(mode="python")
    payload.update(updates)
    return ResourceLease.model_validate(payload)


class LeaseManager:
    def __init__(self, store: IterationPlanStore) -> None:
        self.store = store

    def register(self, lease: ResourceLease) -> ResourceLease:
        self.store.write_lease(lease)
        return lease

    def read(self, run_id: str, lease_id: str) -> ResourceLease:
        return self.store.read_lease(run_id, lease_id)

    def heartbeat(self, lease_id: str, *, owner: str, now: datetime) -> ResourceLease:
        validate_identifier(owner)
        lease = self.store.find_lease(lease_id)
        if lease.owner != owner:
            raise PermissionError("lease heartbeat owner does not match")
        if lease.state is not LeaseState.ACTIVE:
            raise RuntimeError(f"cannot heartbeat lease in state {lease.state.value}")
        updated = _updated_lease(lease, heartbeat_at=now)
        if updated.heartbeat_at < lease.heartbeat_at:
            raise ValueError("lease heartbeat must not move backwards")
        self.store.write_lease(updated)
        return updated

    def inspect(
        self,
        lease_id: str,
        *,
        inspector: ResourceInspector,
        now: datetime,
    ) -> LeaseInspection:
        lease = self.store.find_lease(lease_id)
        observation = inspector.inspect(lease.identity)
        return self._assess(lease, observation, now=now, enforce_ttl=True)

    def cancel(
        self,
        lease_id: str,
        *,
        inspector: ResourceInspector,
        terminator: ResourceTerminator,
        now: datetime,
    ) -> LeaseInspection:
        inspection = self.inspect(lease_id, inspector=inspector, now=now)
        if inspection.decision is not LeaseDecision.MATCHING:
            return inspection
        lease = inspection.lease
        terminated = terminator.terminate(lease.identity, lease.cleanup_strategy)
        if not terminated:
            return inspection.model_copy(
                update={
                    "decision": LeaseDecision.TERMINATION_FAILED,
                    "authority_to_terminate": False,
                    "reason": "exact resource termination failed",
                }
            )
        cancelled = _updated_lease(
            lease,
            state=LeaseState.CANCELLED,
            heartbeat_at=now,
        )
        self.store.write_lease(cancelled)
        return inspection.model_copy(
            update={
                "decision": LeaseDecision.CANCELLED,
                "lease": cancelled,
                "authority_to_terminate": False,
                "reason": "exact owned resource was cancelled",
            }
        )

    def reconcile(
        self,
        *,
        run_id: str,
        inspector: ResourceInspector,
        new_owner: str,
        now: datetime,
    ) -> tuple[LeaseInspection, ...]:
        validate_identifier(new_owner)
        outcomes: list[LeaseInspection] = []
        for lease in self.store.list_leases(run_id):
            observation = inspector.inspect(lease.identity)
            inspection = self._assess(lease, observation, now=now, enforce_ttl=False)
            if inspection.decision is LeaseDecision.MATCHING:
                taken_over = _updated_lease(
                    lease,
                    owner=new_owner,
                    heartbeat_at=now,
                    state=LeaseState.ACTIVE,
                )
                self.store.write_lease(taken_over)
                inspection = inspection.model_copy(
                    update={
                        "decision": LeaseDecision.TAKEN_OVER,
                        "lease": taken_over,
                        "authority_to_terminate": True,
                        "reason": "matching running resource lease was taken over",
                    }
                )
            elif inspection.decision is LeaseDecision.COMPLETED:
                completed = _updated_lease(
                    lease,
                    state=LeaseState.COMPLETED,
                    heartbeat_at=now,
                )
                self.store.write_lease(completed)
                inspection = inspection.model_copy(update={"lease": completed})
            elif inspection.decision is LeaseDecision.IDENTITY_MISMATCH:
                orphaned = _updated_lease(
                    lease,
                    state=LeaseState.ORPHANED_WITHOUT_AUTHORITY,
                    heartbeat_at=now,
                )
                self.store.write_lease(orphaned)
                inspection = inspection.model_copy(update={"lease": orphaned})
            outcomes.append(inspection)
        return tuple(outcomes)

    @staticmethod
    def _assess(
        lease: ResourceLease,
        observation: ResourceObservation,
        *,
        now: datetime,
        enforce_ttl: bool,
    ) -> LeaseInspection:
        if lease.ownership is ResourceOwnership.PROTECTED_EXTERNAL:
            return LeaseInspection(
                decision=LeaseDecision.PROTECTED_EXTERNAL,
                lease=lease,
                observation=observation,
                authority_to_terminate=False,
                reason="resource is protected external state",
            )
        if not _same_identity(lease.identity, observation.identity):
            return LeaseInspection(
                decision=LeaseDecision.IDENTITY_MISMATCH,
                lease=lease,
                observation=observation,
                authority_to_terminate=False,
                reason="resource identity or creation token changed",
            )
        if not observation.running:
            return LeaseInspection(
                decision=LeaseDecision.COMPLETED,
                lease=lease,
                observation=observation,
                authority_to_terminate=False,
                reason="owned resource already completed",
            )
        if lease.state is LeaseState.CANCELLED:
            return LeaseInspection(
                decision=LeaseDecision.CANCELLED,
                lease=lease,
                observation=observation,
                authority_to_terminate=False,
                reason="lease is already cancelled",
            )
        expires_at = lease.heartbeat_at + timedelta(seconds=lease.ttl_seconds)
        if enforce_ttl and now > expires_at:
            return LeaseInspection(
                decision=LeaseDecision.EXPIRED,
                lease=lease,
                observation=observation,
                authority_to_terminate=False,
                reason="lease heartbeat TTL expired",
            )
        return LeaseInspection(
            decision=LeaseDecision.MATCHING,
            lease=lease,
            observation=observation,
            authority_to_terminate=True,
            reason="owned resource identity matches active lease",
        )

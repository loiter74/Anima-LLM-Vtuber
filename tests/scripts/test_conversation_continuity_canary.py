"""Unit tests for the runtime continuity canary orchestration."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from scripts.conversation_continuity_canary import (
    ContinuityCanaryError,
    RuntimeTurn,
    run_continuity_canary,
)

ROOT = Path(__file__).resolve().parents[2]


def test_canary_script_entrypoint_imports_contract() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/conversation_continuity_canary.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr


def _trace(
    trace_id: str,
    *,
    before: int,
    after: int,
    committed: bool,
    actor_role: str,
    source: str,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "attributes": {
            "conversation_scope_kind": "livestream",
            "conversation_window_pairs_before": before,
            "conversation_window_pairs_after": after,
            "conversation_committed": committed,
            "actor_role": actor_role,
            "source": source,
        },
    }


@dataclass
class FakeBoundary:
    public_marker: str
    private_marker: str
    viewer_marker: str
    ready: bool = True
    same_socket: bool = False
    probe_committed: bool = False
    viewer_recalls: bool = True
    leaks_private: bool = False
    connections: int = 0
    replay_flags: list[bool | None] = field(default_factory=list)

    async def readiness(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "profile": "production",
            "acceptance_eligible": True,
            "components": {
                "llm": {
                    "ready": self.ready,
                    "resolved": {
                        "type": "deepseek" if self.ready else "mock",
                        "provider": "deepseek" if self.ready else "mock",
                    },
                }
            },
        }

    async def connect(self) -> str:
        self.connections += 1
        return "socket" if self.same_socket else f"socket-{self.connections}"

    async def disconnect(self) -> None:
        return None

    async def send_developer(self, text: str) -> RuntimeTurn:
        if self.public_marker in text:
            return RuntimeTurn(
                "developer-seed",
                "seeded",
                _trace(
                    "developer-seed",
                    before=0,
                    after=1,
                    committed=True,
                    actor_role="developer",
                    source="developer_console",
                ),
            )
        response = self.viewer_marker
        if self.leaks_private:
            response += self.private_marker
        return RuntimeTurn(
            "developer-followup",
            response,
            _trace(
                "developer-followup",
                before=2,
                after=3,
                committed=True,
                actor_role="developer",
                source="developer_console",
            ),
        )

    async def send_replay(
        self,
        text: str,
        *,
        is_probe: bool | None,
        expected_window_before: int,
    ) -> RuntimeTurn:
        del expected_window_before
        self.replay_flags.append(is_probe)
        if is_probe is None:
            after = 2 if self.probe_committed else 1
            return RuntimeTurn(
                "probe",
                "",
                _trace(
                    "probe",
                    before=1,
                    after=after,
                    committed=self.probe_committed,
                    actor_role="viewer",
                    source="bilibili:danmaku",
                ),
            )
        response = self.public_marker if self.viewer_recalls else "missing"
        if self.leaks_private:
            response += self.private_marker
        return RuntimeTurn(
            "viewer",
            response,
            _trace(
                "viewer",
                before=1,
                after=2,
                committed=True,
                actor_role="viewer",
                source="bilibili:danmaku",
            ),
        )


async def _run(boundary: FakeBoundary) -> dict[str, Any]:
    return await run_continuity_canary(
        boundary,
        run_id="canary-run",
        public_marker=boundary.public_marker,
        private_marker=boundary.private_marker,
        viewer_marker=boundary.viewer_marker,
    )


async def test_canary_runs_default_probe_then_explicit_viewer_and_sanitizes_evidence() -> None:
    boundary = FakeBoundary("PUBLIC-SECRET", "PRIVATE-SECRET", "VIEWER-SECRET")

    evidence = await _run(boundary)
    serialized = json.dumps(evidence)

    assert evidence["status"] == "passed"
    assert boundary.replay_flags == [None, False]
    for marker in (boundary.public_marker, boundary.private_marker, boundary.viewer_marker):
        assert marker not in serialized


@pytest.mark.parametrize(
    ("updates", "error_code"),
    [
        ({"same_socket": True}, "socket_reconnect_failed"),
        ({"probe_committed": True}, "transition_mismatch:replay_probe:window_after"),
        ({"viewer_recalls": False}, "public_fact_not_recalled:viewer_reply"),
        ({"leaks_private": True}, "private_marker_leaked:viewer_reply"),
    ],
)
async def test_canary_structural_failures_return_stable_error_codes(
    updates: dict[str, bool],
    error_code: str,
) -> None:
    boundary = FakeBoundary("PUBLIC", "PRIVATE", "VIEWER")
    for attribute, value in updates.items():
        setattr(boundary, attribute, value)

    evidence = await _run(boundary)

    assert evidence["status"] == "failed"
    assert error_code in evidence["error_codes"]


async def test_canary_rejects_mock_or_unready_provider() -> None:
    boundary = FakeBoundary("PUBLIC", "PRIVATE", "VIEWER", ready=False)

    with pytest.raises(ContinuityCanaryError, match="mock_or_unready_provider"):
        await _run(boundary)


async def test_canary_rejects_missing_trace_fields() -> None:
    boundary = FakeBoundary("PUBLIC", "PRIVATE", "VIEWER")

    async def broken_seed(_text: str) -> RuntimeTurn:
        return RuntimeTurn("broken", "", {"attributes": {}})

    boundary.send_developer = broken_seed  # type: ignore[method-assign]

    with pytest.raises(ContinuityCanaryError, match="trace_fields_missing"):
        await _run(boundary)

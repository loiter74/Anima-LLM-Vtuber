"""Data models for inspection results.

CheckResult: Single check pass/fail with timing and diagnostics.
InspectionReport: Aggregated results from a full inspection run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CheckResult(BaseModel):
    """Result of a single inspection check.

    Attributes:
        name: Unique check identifier (e.g., "health/llm_available")
        ok: True if check passed
        duration_ms: Execution duration in milliseconds
        detail: Arbitrary diagnostic data (event lists, query results, etc.)
        error: Error message if check failed (None if passed)
    """

    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    duration_ms: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def passed(cls, name: str, duration_ms: float = 0.0, **detail: Any) -> CheckResult:
        """Create a passing check result with optional detail."""
        return cls(name=name, ok=True, duration_ms=duration_ms, detail=dict(detail))

    @classmethod
    def failed(
        cls, name: str, duration_ms: float = 0.0, error: str = "", **detail: Any
    ) -> CheckResult:
        """Create a failing check result with error message and optional detail."""
        return cls(
            name=name,
            ok=False,
            duration_ms=duration_ms,
            detail=dict(detail),
            error=error,
        )


class InspectionReport(BaseModel):
    """Aggregated report from a full inspection run.

    Attributes:
        run_id: Unique identifier for this inspection run (UUID)
        started_at: Unix timestamp when inspection started
        finished_at: Unix timestamp when inspection completed
        checks: Mapping of check name → CheckResult
        overall_ok: True only if ALL checks pass
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = Field(default_factory=lambda: datetime.now(UTC).timestamp())
    finished_at: float = 0.0
    checks: dict[str, CheckResult] = Field(default_factory=dict)

    @property
    def overall_ok(self) -> bool:
        """True only if every check passed."""
        if not self.checks:
            return False
        return all(c.ok for c in self.checks.values())

    @property
    def summary(self) -> str:
        """Human-readable one-line summary."""
        total = len(self.checks)
        passed = sum(1 for c in self.checks.values() if c.ok)
        failed = total - passed
        if failed == 0:
            return f"[{self.run_id[:8]}] All {total} checks passed ✓"
        failed_names = ", ".join(name for name, c in self.checks.items() if not c.ok)
        return f"[{self.run_id[:8]}] {passed}/{total} passed · Failed: {failed_names}"

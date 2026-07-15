"""Daily inspection system — proactive end-to-end verification.

Provides:
- run_full_inspection() — public entry point for manual or scheduled runs
- InspectionScheduler — background asyncio.Task for daily inspection
- CheckResult / InspectionReport — data models
"""

__all__ = [
    "CheckResult",
    "InspectionReport",
    "InspectionScheduler",
    "run_full_inspection",
]

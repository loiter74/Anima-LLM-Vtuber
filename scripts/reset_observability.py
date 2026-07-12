#!/usr/bin/env python3
"""Delete disposable observation databases and bootstrap schema version 2."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from animetta.observability.ledger import SQLiteObservationLedger


async def reset_observability_data(data_dir: Path) -> Path:
    """Remove legacy/current SQLite files and create one empty canonical ledger."""
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "stats.db",
        "stats.db-wal",
        "stats.db-shm",
        "observations.db",
        "observations.db-wal",
        "observations.db-shm",
    ):
        path = (data_dir / name).resolve()
        if path.parent != data_dir:
            raise RuntimeError("refusing to reset a path outside the data directory")
        path.unlink(missing_ok=True)

    ledger_path = data_dir / "observations.db"
    ledger = SQLiteObservationLedger(ledger_path)
    await ledger.start()
    await ledger.close()
    return ledger_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
    )
    args = parser.parse_args()
    ledger_path = asyncio.run(reset_observability_data(args.data_dir))
    print(f"Observation ledger reset: {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

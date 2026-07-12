from __future__ import annotations

import sqlite3

from scripts.reset_observability import reset_observability_data


async def test_reset_removes_legacy_data_and_bootstraps_schema_v2(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "stats.db").write_bytes(b"obsolete")
    (data_dir / "observations.db").write_bytes(b"obsolete")

    path = await reset_observability_data(data_dir)

    assert not (data_dir / "stats.db").exists()
    assert path.is_file()
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT version FROM observation_schema"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert version == (2,)
    assert {
        "observation_traces",
        "observation_operations",
        "observation_events",
        "inspection_reports",
    } <= tables

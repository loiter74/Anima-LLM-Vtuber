import sqlite3

from animetta.observability.ledger.sqlite import SQLiteObservationLedger


async def test_ledger_creates_versioned_schema_with_foreign_keys(tmp_path) -> None:
    db_path = tmp_path / "observations.db"
    ledger = SQLiteObservationLedger(db_path)

    await ledger.start()
    await ledger.close()

    connection = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        operation_fks = connection.execute(
            "PRAGMA foreign_key_list(observation_operations)"
        ).fetchall()
        event_fks = connection.execute(
            "PRAGMA foreign_key_list(observation_events)"
        ).fetchall()
        schema_version = connection.execute(
            "SELECT version FROM observation_schema"
        ).fetchone()
    finally:
        connection.close()

    assert {
        "observation_schema",
        "observation_traces",
        "observation_operations",
        "observation_events",
        "inspection_reports",
    } <= tables
    assert {
        "idx_observation_traces_started",
        "idx_observation_operations_trace",
        "idx_observation_operations_parent",
        "idx_observation_events_trace",
    } <= indexes
    assert any(row[2] == "observation_traces" and row[3] == "trace_id" for row in operation_fks)
    assert any(row[2] == "observation_traces" and row[3] == "trace_id" for row in event_fks)
    assert schema_version == (2,)

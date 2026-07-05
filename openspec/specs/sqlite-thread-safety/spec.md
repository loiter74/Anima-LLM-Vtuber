# sqlite-thread-safety Specification

## Purpose
TBD - created by archiving change fix-startup-bugs-parallel. Update Purpose after archive.
## Requirements
### Requirement: SQLite connection allows cross-thread access

The `SQLiteStore` SHALL create its `sqlite3.Connection` with `check_same_thread=False` to permit access from threads other than the creating thread.

#### Scenario: Connection created with cross-thread flag

- **WHEN** `SQLiteStore.__init__()` calls `sqlite3.connect(db_path)`
- **THEN** the connection SHALL have `check_same_thread=False` set

### Requirement: Concurrent writes protected by lock

All `self.conn.execute()` and `self.conn.commit()` calls in `SQLiteStore` SHALL be serialized through a `threading.Lock` to prevent data corruption from concurrent access.

#### Scenario: Event-loop write concurrent with thread-pool write

- **WHEN** the event-loop thread (via `store_turn` → `ingest_turn` → `_index_file`) writes to SQLite while the thread-pool worker (via `maintain_pool` → `_index_file`) simultaneously writes to SQLite
- **THEN** both writes SHALL complete without `SQLite objects created in a thread` error or `database is locked` error

### Requirement: Lock is reentrant for nested calls

The lock SHALL be reentrant (`threading.RLock`) to support nested calls within the same thread (e.g., `_index_file` which calls multiple `self.sqlite.*` methods).

#### Scenario: Same thread makes nested SQLite calls

- **WHEN** `_index_file()` calls `self.sqlite.delete_chunks_by_path()` then `self.sqlite.upsert_file()` then `self.sqlite.insert_chunks()` in sequence
- **THEN** all calls SHALL succeed without deadlock

### Requirement: Lock is applied at the store level

The lock SHALL be acquired inside each public method of `SQLiteStore` (not at the caller level) to ensure comprehensive protection regardless of call chain.

#### Scenario: Direct caller does not manage locks

- **WHEN** any code calls `sqlite_store.upsert_file(entry)` without manually acquiring any lock
- **THEN** the store method SHALL internally acquire and release its lock, completing the operation safely

### Requirement: Performance impact is negligible

The lock SHALL NOT introduce measurable latency under normal single-threaded usage patterns.

#### Scenario: Single-threaded access shows no degradation

- **WHEN** a single conversation turn stores data, triggering `_index_file` once
- **THEN** the total operation time SHALL NOT increase by more than 1ms compared to the non-locked baseline

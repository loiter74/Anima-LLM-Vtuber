## Purpose
Defines the accepted behavior and requirements for the redis-session-sharing capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Redis checkpoint via CLI flag
The system SHALL accept an optional `--redis-url` CLI argument. When provided, LangGraph checkpoints SHALL be stored in Redis using `AsyncRedisSaver`. When absent, the existing in-memory `MemorySaver` SHALL be used.

#### Scenario: Redis checkpoint enabled
- **WHEN** server starts with `--redis-url redis://localhost:6379`
- **THEN** LangGraph StateGraph is built with `AsyncRedisSaver`
- **AND** all session state is persisted in Redis
- **AND** session survives backend restart

#### Scenario: Default in-memory checkpoint
- **WHEN** server starts without `--redis-url`
- **THEN** existing `MemorySaver` is used
- **AND** behavior is identical to current system

### Requirement: Multi-instance session continuity
When Redis checkpoint is enabled and multiple backend instances share the same Redis URL, the system SHALL allow a client to connect to any instance and resume their session transparently.

#### Scenario: Session resumed on different instance
- **WHEN** user creates session on instance A
- **AND** user reconnects and is routed to instance B
- **THEN** instance B loads session state from Redis
- **AND** conversation history and context are preserved

### Requirement: Redis connection failure is non-fatal
If Redis is unreachable at startup with `--redis-url` specified, the system SHALL log a warning and fall back to `MemorySaver` rather than refusing to start.

#### Scenario: Redis unreachable
- **WHEN** server starts with `--redis-url redis://nonexistent:6379`
- **THEN** a warning is logged: "Redis unavailable, falling back to in-memory checkpoint"
- **AND** server starts with in-memory `MemorySaver`

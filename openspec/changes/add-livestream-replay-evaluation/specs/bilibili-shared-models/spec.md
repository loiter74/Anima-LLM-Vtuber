## ADDED Requirements

### Requirement: Normalized livestream event model
The system SHALL provide a frozen shared `LivestreamEvent` model and `LivestreamEventType` enumeration for danmaku, gift, super chat, entry, follow, batched likes, popularity snapshots, connection state, and unknown commands.

#### Scenario: Serialize a normalized event
- **WHEN** a `LivestreamEvent` is converted to a dictionary
- **THEN** the result contains `sequence`, `offset_ms`, `event_type`, `actor_id`, `text`, and `payload` using JSON-compatible values

#### Scenario: Convert a replyable event
- **WHEN** a danmaku, gift, or super-chat event is converted to a legacy message
- **THEN** the resulting `DanmakuMessage` preserves text, actor identity, timestamp, gift/super-chat flags, and whitelisted metadata

#### Scenario: Ignore a non-replyable event
- **WHEN** an entry, follow, like, popularity, connection, or unknown event is converted to a legacy message
- **THEN** the conversion returns no message

### Requirement: Separate livestream event metrics
The system SHALL track livestream event counts and dispatch failures separately from existing AI reply metrics.

#### Scenario: Count all normalized events
- **WHEN** a normalized event reaches `LivestreamSession`
- **THEN** event metrics increment the total and per-type received counters
- **AND** existing `ReplyMetrics.received` changes only for replyable messages

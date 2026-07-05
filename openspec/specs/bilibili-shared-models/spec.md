## Purpose
Defines the accepted behavior and requirements for the bilibili-shared-models capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Unified danmaku message model
The system SHALL provide a single `DanmakuMessage` dataclass in `services.bilibili.models` that represents all danmaku types (text, gift, super chat) with unified field names.

#### Scenario: Plain text danmaku
- **WHEN** a text-only danmaku is received from a Bilibili live room
- **THEN** the system creates a `DanmakuMessage` with `text`, `user_name`, `user_id`, `timestamp` populated, and `is_gift=False`, `is_super_chat=False`

#### Scenario: Gift event
- **WHEN** a SEND_GIFT event is received
- **THEN** the system creates a `DanmakuMessage` with `text="感谢 {user} 送出的 {n} 个 {gift}", is_gift=True` and gift metadata in `meta` dict

#### Scenario: Super Chat event
- **WHEN** a SUPER_CHAT_MESSAGE event is received
- **THEN** the system creates a `DanmakuMessage` with `text="SC ¥{price}: {message}", is_super_chat=True` and price metadata in `meta` dict

### Requirement: Consolidated dataclass location
All shared bilibili-related dataclasses (`DanmakuMessage`, `DanmakuReply`, `DanmakuPhrase`, `CollectedVideo`, `CollectedComment`, `MemeCandidate`, `InteractionPattern`, `LivestreamStrategy`) SHALL be defined in `services/bilibili/models.py` and imported by service classes rather than being redefined locally.

#### Scenario: Service class imports models
- **WHEN** `DanmakuService` needs `DanmakuMessage`
- **THEN** it imports from `services.bilibili.models` without defining any local dataclass

### Requirement: Backward-compatible model changes
The unified `DanmakuMessage` SHALL be backward-compatible with existing code that only accesses `text`, `user_name`, `user_id`, `timestamp` fields.

#### Scenario: Existing handler accesses core fields
- **WHEN** `bilibili_handlers.py` accesses `msg.text`, `msg.user_name`, `msg.user_id`
- **THEN** these fields work identically to before the refactoring

# turn-cache Specification

## Purpose
TBD - created by archiving change supermemory-memory-enhancement. Update Purpose after archive.
## Requirements
### Requirement: Per-turn 記憶檢索快取

系統 SHALL 在 MemorySystem 中提供一個輪次級快取機制 `_turn_cache`，避免同一輪中重複的記憶檢索。

快取實現 SHALL：
- key = `sha256(session_id + ":" + user_input)`
- value = 檢索結果（序列化字串或物件）
- 每輪開始（新 user_input）時自動清空
- 線程安全（使用 `threading.Lock` 或 `asyncio.Lock`）

#### Scenario: 同輪去重

- **WHEN** 同一輪中 Agent 多次呼叫 `retrieve_context()`（如同輪多個 tool call）
- **THEN** 第二次及後續呼叫直接返回快取結果，不重複查詢 SQLite 或 Chroma

#### Scenario: 跨輪隔離

- **WHEN** 新一輪對話開始（新 user_input）
- **THEN** 快取自動清空
- **THEN** 新輪首次 `retrieve_context()` 重新查詢

### Requirement: 快取排除配置

系統 SHALL 支援配置哪些檢索參數不參與快取（如 `max_turns`、`min_score` 等過濾參數變化時需重新查詢）。

#### Scenario: 參數變化重新查詢

- **WHEN** 同一輪中 `retrieve_context()` 被用不同 `max_turns` 參數呼叫
- **THEN** 系統以完整參數組合建 key，而非僅 user_input
- **THEN** 參數不同的呼叫不命中同一個快取

# user-profile Specification

## Purpose
TBD - created by archiving change supermemory-memory-enhancement. Update Purpose after archive.
## Requirements
### Requirement: User Profile 資料模型

系統 SHALL 提供 `UserProfile` 資料模型，包含兩個部分：

- `static`: `List[str]` — 長期穩定的事實描述，如 `["喜歡 TypeScript", "使用 Vim", "住在上海"]`
- `dynamic`: `List[str]` — 當前對話上下文的動態資訊，如 `["正在調試 API 限流問題", "剛問了關於 Live2D 的問題"]`

系統 SHALL 提供 `get_profile(session_id) -> UserProfile` 方法。

#### Scenario: Static Profile 從 wiki 自動提煉

- **WHEN** 系統建構 static profile
- **THEN** 從 `wiki/entities/` 和 `wiki/concepts/` 中自動提取使用者相關的長期事實

#### Scenario: Dynamic Profile 從短期記憶建構

- **WHEN** 系統建構 dynamic profile
- **THEN** 從 ShortTermMemory 中該 session 最近 N 輪（預設 5 輪）對話內容提煉當前上下文摘要

### Requirement: Profile 與記憶檢索整合

`UserProfile` SHALL 在每次 `retrieve_context()` 呼叫時一併傳回。

系統在注入記憶到 system prompt 時，SHALL 同時包含 UserProfile 內容。

#### Scenario: 記憶注入包含 Profile

- **WHEN** `MemoryMiddleware.before_llm_call` 執行
- **THEN** 注入的 system prompt 中包含 `## 用戶畫像` 區塊
- **THEN** 內容同時列出 static 和 dynamic 資訊

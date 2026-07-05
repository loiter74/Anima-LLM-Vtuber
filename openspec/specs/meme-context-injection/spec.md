# meme-context-injection Specification

## Purpose
在对话中基于语义匹配将合适的梗注入 LLM 上下文，让 AI 在对话中自然接梗。

Defines the accepted behavior and requirements for the meme-context-injection capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements

### Requirement: 语义匹配替代关键词匹配
系统 SHALL 升级 `MemePool.select_for_context()` 方法，从简单关键词匹配改为语义匹配。

#### Scenario: 语义匹配执行
- **WHEN** 对话需要选择合适的梗注入上下文
- **THEN** 系统 SHALL 使用 Hybrid Search（Chroma 向量相似度 + SQLite BM25）匹配用户输入
- **AND** 检索 MemePool 中的所有活跃梗
- **AND** 返回 current_score 最高的匹配梗

#### Scenario: 无合适梗匹配
- **WHEN** 语义匹配未找到相关性足够的梗（persona_fit_score < 0.5 或 vector similarity < 阈值）
- **THEN** 系统 SHALL 返回 None
- **AND** 不注入任何梗到上下文

### Requirement: 梗上下文注入
系统 SHALL 在 LLM 对话上下文中注入匹配到的梗信息。

#### Scenario: 梗信息注入
- **WHEN** `select_for_context()` 返回匹配的 Meme
- **THEN** 系统 SHALL 将梗信息注入 LLM system prompt
- **AND** 注入格式 SHALL 包含：梗文本、使用场景提示（context_hint）、使用示例（usage_example）
- **AND** 注入内容 SHALL 标记为 `[MemeContext]` 以便后续追溯

#### Scenario: 梗注入不影响正常对话
- **WHEN** 梗信息注入到 LLM 上下文
- **THEN** 注入内容 SHALL 不覆盖原有 system prompt
- **AND** 不强制 LLM 必须使用该梗（仅作为可选参考）

### Requirement: 梗使用后反馈
系统 SHALL 在 AI 使用梗后收集反馈，用于更新梗的评分。

#### Scenario: 使用梗后触发评分更新
- **WHEN** AI 在回复中使用了 MemePool 中的梗
- **THEN** 系统 SHALL 调用 `MemePool.score_after_use(meme_id, effectiveness)`
- **AND** effectiveness 初始值 SHALL 为 0.5（中性评分）

#### Scenario: 用户反馈影响梗评分
- **WHEN** 用户对含梗回复表现出积极反应（如继续讨论梗话题、发送积极表情）
- **THEN** 系统 MAY 提升 effectiveness 值
- **WHEN** 用户表现出困惑或负面反应
- **THEN** 系统 MAY 降低 effectiveness 值

### Requirement: B 站来源标识
系统 SHALL 在梗数据中标识来源平台，支持按来源筛选。

#### Scenario: 来源字段持久化
- **WHEN** 梗通过 BilibiliMemeCollector 入库
- **THEN** Meme 的 `source_platform` 字段 SHALL 设为 `"bilibili"`
- **AND** cognitive_analysis.source_url SHALL 包含 B 站视频链接

#### Scenario: 按来源筛选
- **WHEN** 需要只获取 B 站来源的梗
- **THEN** 系统 SHALL 支持按 `source_platform == "bilibili"` 过滤

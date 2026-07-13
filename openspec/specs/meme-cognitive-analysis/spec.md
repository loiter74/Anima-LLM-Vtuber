# meme-cognitive-analysis Specification

## Purpose
使用 LLM 对采集到的梗进行认知科学分析，输出幽默机制、使用场景、情感色彩等结构化描述，存入 Meme 模型供 AI 对话时使用。
## Requirements
### Requirement: 梗认知分析
系统 SHALL 对每个梗候选执行 LLM 驱动的认知分析，输出结构化分析结果。

#### Scenario: 认知分析执行
- **WHEN** BilibiliMemeCollector 产出梗候选列表
- **THEN** 系统调用 LLM 进行认知分析
- **AND** LLM 的 system prompt 要求输出 JSON 格式
- **AND** 分析维度 SHALL 包含：幽默机制（humor_mechanism）、触发场景（context_trigger）、情感色彩（emotional_tone）、人设匹配度（persona_fit_score）、使用示例（usage_example）

#### Scenario: 认知分析 JSON Schema 校验
- **WHEN** LLM 返回认知分析结果
- **THEN** 系统 SHALL 校验 JSON 格式的完整性
- **AND** 必填字段缺失时标记该候选为"分析失败"
- **AND** persona_fit_score SHALL 为 0-1 之间的浮点数

#### Scenario: 认知分析失败降级
- **WHEN** LLM 调用失败或返回无法解析的结果
- **THEN** 系统 SHALL 创建仅有基础字段（text + context_hint）的 Meme
- **AND** cognitive_analysis 字段设为 None
- **AND** 记录 warning 日志

### Requirement: CognitiveAnalysis 数据模型
系统 SHALL 定义 `CognitiveAnalysis` 数据类存储认知分析结果，并作为 Meme 模型的可选字段。

#### Scenario: CognitiveAnalysis 字段完整性
- **WHEN** 创建 CognitiveAnalysis 实例
- **THEN** 实例 SHALL 包含以下字段：
  - `humor_mechanism: str` — 如 "双关", "反讽", "荒诞", "自指", "谐音", "反差"
  - `context_trigger: str` — 触发场景描述
  - `emotional_tone: str` — 如 "幽默", "讽刺", "自嘲", "温暖", "荒诞"
  - `persona_fit_score: float` — 0-1 与当前人设匹配度
  - `usage_example: str` — 对话中使用示例
  - `source_url: str` — B 站视频链接

### Requirement: 梗分析结果入库
系统 SHALL 将认知分析完成的梗通过 MemePool 的 `add_from_candidate()` 方法存入 MemePool。

#### Scenario: 高信心梗入库
- **WHEN** 认知分析完成且 persona_fit_score >= 0.5
- **THEN** 系统 SHALL 调用 `MemePool.add_from_candidate()` 入库
- **AND** confidence 参数设为 persona_fit_score 值

#### Scenario: 低信心梗跳过
- **WHEN** 认知分析完成但 persona_fit_score < 0.5
- **THEN** 系统 SHALL 跳过该候选，不入库
- **AND** 记录 debug 日志

### Requirement: 梗风格元数据保留
系统 SHALL 在认知分析和入库流程中保留已匹配的梗风格元数据。

#### Scenario: 认知分析接收风格元数据
- **WHEN** MemeCognitiveAnalyzer 分析带有 `format_id` 和 `format_slots` 的候选
- **THEN** 认知分析结果 SHALL 保留 `format_id` 作为 meme style id
- **AND** 认知分析结果 SHALL 保留 `format_slots`
- **AND** 如存在 `rendered_text`，认知分析结果 SHALL 将其作为格式化使用示例的候选来源

#### Scenario: 周礼体示例进入 usage_example
- **WHEN** 候选的 `format_id` 为 `zhouli` 且 `rendered_text` 有效
- **THEN** CognitiveAnalysis 的 `usage_example` SHALL 优先使用或包含该周礼体格式化示例
- **AND** `humor_mechanism` SHALL 能表达其 mock-classical ritual elevation mechanism

#### Scenario: 入库保留风格标签
- **WHEN** 带格式元数据的候选通过 persona_fit_score 门槛并入库
- **THEN** Meme SHALL 保留 `format_id` 和 `format_slots`
- **AND** Meme tags SHALL include `format:<format_id>`

#### Scenario: Review payload exports format metadata
- **WHEN** meme review API or Socket.IO handler serializes a meme with format metadata
- **THEN** the payload SHALL include `format_id`, `format_slots`, optional `format_confidence`, and optional `rendered_text`
- **AND** memes without format metadata SHALL serialize successfully without those fields

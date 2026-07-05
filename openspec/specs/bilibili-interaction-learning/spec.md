# bilibili-interaction-learning Specification

## Purpose
分析 B 站直播间的弹幕互动模式（回应节奏、梗使用时机、观众情绪响应），生成直播优化策略，帮助 Anima 在直播中表现更贴近真人主播。

## Requirements

### Requirement: 弹幕互动模式采集
系统 SHALL 从 B 站热门直播间采集弹幕互动数据用于模式分析。

#### Scenario: 弹幕数据采集
- **WHEN** PeriodicLearner 触发 `learn_interaction_patterns()` 调度任务
- **THEN** 系统连接指定的 B 站热门直播间（可配置 room_id 列表）
- **AND** 每个直播间采集至少 100 条弹幕消息
- **AND** 记录每条弹幕的时间戳、内容、用户类型（新观众/老粉/舰长等）

#### Scenario: 采集样本不足
- **WHEN** 某直播间弹幕数不足 100 条
- **THEN** 系统 SHALL 跳过该直播间的分析
- **AND** 记录 info 日志说明样本不足

### Requirement: 交互模式分析
系统 SHALL 使用 LLM 分析弹幕交互数据，提取互动模式。

#### Scenario: 互动模式分析
- **WHEN** 完成弹幕数据采集
- **THEN** 系统调用 LLM 分析以下维度：
  - 主播回应频率分布（高频/中频/低频回应的比例）
  - 梗使用时机（弹幕高潮期/冷场期/特定话题触发）
  - 观众情感流动曲线（积极情绪 vs 消极情绪的时间分布）
  - 互动类型分类（问答型/调侃型/情感共鸣型/信息型）

#### Scenario: 互动模式结构化输出
- **WHEN** LLM 分析完成
- **THEN** 系统 SHALL 输出 `InteractionPattern` 结构化数据
- **AND** 数据 SHALL 包含：模式名称、模式描述、适用场景、置信度评分

### Requirement: 直播优化策略生成
系统 SHALL 基于分析出的交互模式生成可操作的直播优化策略。

#### Scenario: 策略生成
- **WHEN** 交互模式分析完成
- **THEN** 系统 SHALL 生成具体的直播行为建议
- **AND** 每条建议 SHALL 包含：触发条件、建议行为、预期效果、优先级（高/中/低）

#### Scenario: 策略存储
- **WHEN** 直播优化策略生成完成
- **THEN** 系统 SHALL 将策略存储为 Wiki 页面（PageType: CONCEPT, path: `wiki/concepts/livestream-strategy.md`）
- **AND** 策略可通过 Hybrid Search 检索

### Requirement: 弹幕采集安全
系统 SHALL 在弹幕数据采集中遵守 API 限制并保护用户隐私。

#### Scenario: API 限流遵守
- **WHEN** 连接 B 站直播间获取弹幕
- **THEN** 系统 SHALL 遵守 bilibili-api-python 的内置限流机制
- **AND** 单次采集不超过 3 个直播间

#### Scenario: 用户数据匿名化
- **WHEN** 存储弹幕交互数据
- **THEN** 系统 SHALL 不存储用户 UID 和个人身份信息
- **AND** 仅保留弹幕内容和时间戳用于模式分析

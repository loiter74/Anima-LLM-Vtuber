# proactive-chat Specification

## Purpose
TBD - created by archiving change minecraft-ai-autonomous-builder. Update Purpose after archive.
## Requirements
### Requirement: Proactive chat triggers
系统 SHALL 基于环境事件和规则触发主动聊天，无需 LLM 指令。

#### Scenario: Player nearby triggers chat
- **WHEN** 附近 20 格内有玩家
- **AND** 聊天冷却已过
- **AND** 概率触发通过检查
- **THEN** Bot SHALL 发送 rules.md 中对应场景的聊天消息

#### Scenario: Weather/time triggers chat
- **WHEN** 天气变化（开始下雨）或时间变化（入夜）
- **AND** 聊天冷却已过
- **THEN** Bot SHALL 可选择触发对应话题的聊天

#### Scenario: Build progress chat
- **WHEN** 一个建造步骤完成
- **THEN** Bot SHALL 可选择发送进度报告聊天消息

### Requirement: Chat cooldown
系统 SHALL 限制主动聊天频率，避免刷屏。

#### Scenario: Chat cooldown respected
- **WHEN** Bot 刚发送过主动聊天消息
- **THEN** 30 秒内 SHOULD NOT 再次触发主动聊天

### Requirement: Context-aware chat messages
聊天消息 SHALL 根据当前上下文（玩家、进度、环境）动态生成或从模板选择。

#### Scenario: Message from template
- **WHEN** 触发 player_nearby 聊天
- **THEN** Bot SHALL 从对应话题的消息列表中随机选择一条发送

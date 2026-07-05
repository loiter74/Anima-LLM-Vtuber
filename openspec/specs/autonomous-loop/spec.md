## Purpose
Defines the accepted behavior and requirements for the autonomous-loop capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Autonomous decision loop
系统 SHALL 实现一个自主决策循环，作为 LLM 规划不可用时的后备行为模式。当 Bot 无活跃 LLM 指令且 planner 未执行时，定期评估环境并选择下一行为。当学习组件可用时，循环 SHALL 包含技能匹配、轨迹记录和技能提取。

#### Scenario: Loop triggers at idle
- **WHEN** Bot 完成上一个动作且无 LLM 指令排队
- **AND** 当前模式不是 planner 模式
- **THEN** 自主循环 SHALL 在 3-8 秒内触发一次评估

#### Scenario: LLM instruction preempts autonomous loop
- **WHEN** LLM 发送新指令（set_mode: planner）
- **THEN** 自主循环 SHALL 暂停，状态机进入 planner 模式
- **AND** planner 模式完成或失败后恢复自主循环

#### Scenario: Loop evaluates state before deciding
- **WHEN** 自主循环触发
- **THEN** Bot SHALL 先获取完整状态（位置、血量、食物、库存、附近实体、时间、天气）
- **AND** 基于状态 + rules.md 规则选择行为

#### Scenario: Action timeout reset
- **WHEN** 某个动作执行超过 30 秒无响应
- **THEN** 系统 SHALL 标记超时并重置 Bot 状态
- **AND** 触发新的评估

#### Scenario: Skill matching in evaluate
- **WHEN** skill_library is available and match_skills() returns a matching skill
- **THEN** _evaluate() SHALL return ACTION_EXECUTE_SKILL with the skill_id
- **AND** this SHALL take priority over maintenance, chat, and explore actions

#### Scenario: Trace recording in execute
- **WHEN** trace_recorder is available and an action executes
- **THEN** the system SHALL call recorder.start_trace() before execution
- **AND** recorder.record_action() with state_before/state_after after execution
- **AND** recorder.end_trace() with success/failure status

#### Scenario: Skill extraction on success
- **WHEN** an action succeeds AND skill_extractor is available
- **THEN** the system SHALL trigger _trigger_skill_extraction() as an async background task
- **AND** the extractor SHALL check for duplicates before calling the LLM

### Requirement: Behavior priority system
系统 SHALL 支持基于优先级的决策，高优先级行为打断低优先级。当学习组件可用时，技能匹配 SHALL 在生存检查之后、维护检查之前执行。

#### Scenario: Survival overrides building
- **WHEN** Bot 血量低于 safety.auto_heal_threshold
- **THEN** 所有建造/收集行为 SHALL 暂停
- **AND** Bot SHALL 执行回血行为（吃食物/回到安全位置）

#### Scenario: Night safety override
- **WHEN** 游戏时间为夜晚且 rules.md 中 return_to_base_at_night 为 true
- **THEN** Bot SHALL 停止户外活动并返回基地

#### Scenario: Skill match overrides maintenance
- **WHEN** skill_library returns a matching skill for current context
- **AND** no survival action is needed
- **THEN** the skill SHALL be executed before any maintenance, chat, or explore action

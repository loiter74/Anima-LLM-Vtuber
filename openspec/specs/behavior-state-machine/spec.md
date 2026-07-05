# behavior-state-machine Specification

## Purpose
TBD - created by archiving change mc-bot-smart-brain. Update Purpose after archive.
## Requirements
### Requirement: State-based behavior execution
系统 SHALL 使用 mineflayer-statemachine 在 Node.js 侧管理行为状态，每个行为作为独立状态节点。

#### Scenario: State transition on condition
- **WHEN** Bot 处于"收集"状态
- **AND** 材料收集完毕
- **THEN** 状态机 SHALL 自动转换到"建造"状态

#### Scenario: Emergency interrupt
- **WHEN** Bot 处于任何非战斗状态
- **AND** 附近出现敌对实体
- **THEN** 状态机 SHALL 切换到"战斗"状态，战斗结束后回到之前状态

### Requirement: Mode switching
系统 SHALL 支持 Python 侧通过协议命令切换执行模式。

#### Scenario: Switch to planner mode
- **WHEN** Python 侧发送 set_mode(planner, plan)
- **THEN** 状态机 SHALL 按 plan 序列依次执行子任务

#### Scenario: Switch to rule mode
- **WHEN** Python 侧发送 set_mode(rule)
- **THEN** 状态机 SHALL 进入闲置状态，由 Python 的 autonomous-loop 逐条发指令

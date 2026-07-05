# llm-planner Specification

## Purpose
TBD - created by archiving change mc-bot-smart-brain. Update Purpose after archive.
## Requirements
### Requirement: Natural language goal decomposition
系统 SHALL 接收自然语言目标，通过 LLM 分解为可执行的子任务序列。

#### Scenario: Simple building goal
- **WHEN** 用户说"在我旁边建个小房子"
- **THEN** LLM SHALL 输出子任务序列，每个子任务映射到已有工具（如 smart_goto, smart_collect, smart_build）

#### Scenario: Unknown goal fallback
- **WHEN** LLM 无法将目标映射到已知工具
- **THEN** 系统 SHALL 返回可用的工具列表和建议重新表述

### Requirement: Dynamic replanning
系统 SHALL 在子任务执行失败时自动重新规划剩余步骤。

#### Scenario: Material shortage triggers replan
- **WHEN** 执行"建造"子任务时发现材料不足
- **THEN** LLM SHALL 插入"收集缺失材料"子任务
- **AND** 保持已完成的步骤不重复执行

### Requirement: Dual-mode operation
系统 SHALL 支持 LLM 规划模式和规则后备模式自动切换。

#### Scenario: LLM unavailable falls back to rules
- **WHEN** LLM 服务不可用或规划超时
- **THEN** 系统 SHALL 自动切换到 autonomous-loop 的规则模式

# behavior-rules Specification

## Purpose
TBD - created by archiving change minecraft-ai-autonomous-builder. Update Purpose after archive.
## Requirements
### Requirement: Rules file format
系统 SHALL 支持 YAML 格式的 rules.md 文件，定义 AI 自主行为规则。

#### Scenario: Load rules on startup
- **WHEN** AutonomousLoop 初始化
- **THEN** 系统 SHALL 读取 `src/anima/tools/minecraft/rules.md`
- **AND** 解析为内部配置对象
- **AND** 解析失败时使用安全默认值并记录告警

#### Scenario: Rules override defaults
- **WHEN** rules.md 中的配置项有效
- **THEN** 对应配置项 SHALL 覆盖系统默认值

### Requirement: Character personality definition
rules.md SHALL 定义角色名称、性格描述和对话风格。

#### Scenario: Personality affects chat style
- **WHEN** AI 触发主动聊天
- **THEN** 消息风格 SHALL 符合 personality 字段描述（如"友好的建造者"）

### Requirement: Building blueprint definition
rules.md SHALL 支持定义建筑目标蓝图，包含所需材料和建造步骤。

#### Scenario: Blueprint parsed correctly
- **WHEN** rules.md 中 building 段配置完整
- **THEN** 系统 SHALL 正确解析 target、required_materials、build_plan 等字段

### Requirement: Safety configuration
rules.md SHALL 支持安全相关配置，且安全硬编码优先级高于 rules.md。

#### Scenario: Safety hardcodes override rules
- **WHEN** rules.md 中 max_distance 大于 config/tools.yaml 中的值
- **THEN** 系统 SHALL 使用 config/tools.yaml 中较小的值
- **AND** 记录配置冲突告警

## ADDED Requirements

### Requirement: 所有动作共享可取消操作作用域
mc-mcp SHALL 向每个 capability 传播 signal 和 deadline，并 SHALL 在 terminal 前停止或隔离 pathfinder、dig、PVP、controls、container 和等待资源。

#### Scenario: 中途取消普通动作
- **WHEN** 正在运行的非容器 action 接受取消
- **THEN** 底层资源在 2 秒内静止并进入 terminal，否则系统记录 `CANCEL_SETTLEMENT_TIMEOUT`、标记世界可能变化并 quarantine

#### Scenario: 中途取消容器动作
- **WHEN** craft 或 smelt 的容器处于打开状态并接受取消
- **THEN** 系统关闭容器并在 3 秒内进入 terminal，否则进入 quarantine

#### Scenario: 导航超时
- **WHEN** pathfinder 未满足目标 predicate 即达到 deadline
- **THEN** action 不得报告成功，process busy 在底层静止或 quarantine 前不得释放

### Requirement: 动作阶段事件事实化且有界
mc-mcp SHALL 为 action 输出受限阶段事件，按 correlation 单调编号、去重和限频，并 MUST NOT 用事件决定 action 成败或输出心理文本。

#### Scenario: 长时间等待动作
- **WHEN** action 连续等待超过 5 秒
- **THEN** waiting heartbeat 最多每 5 秒一条，且整个 correlation 不超过 32 条事件

#### Scenario: 重复 correlation
- **WHEN** runtime 收到相同 correlation 的 in-flight 或 terminal 重试
- **THEN** 系统复用原 promise/receipt，并且不重演动作或历史阶段

### Requirement: 头部表现不改变任务语义
BroadcastMotionPolicy SHALL 只注视真实目标和执行有界短停，MUST NOT 改变目标、路径、控制键、水平位置、方块、背包或战斗决策。

#### Scenario: 安全窗口中的放置
- **WHEN** bot 安全、deadline 充足且 place 尚未进入最终交互瞄准
- **THEN** 表现层可以粗略注视目标并短停，最终瞄准仍由 place capability 独占，放置后观察真实结果

#### Scenario: 危险或战斗状态
- **WHEN** bot 正在战斗、坠落、处于流体、低生命/饱食、近敌、取消或 deadline 少于 2 秒
- **THEN** 所有额外 gaze 和 dwell 为零，只保留事实阶段事件

### Requirement: 表现节拍确定且受预算限制
系统 SHALL 从配置 seed、correlation、capability、phase 和 ordinal 派生节拍，不得使用全局随机状态，并 SHALL 遵守 brisk 600ms、normal 900ms、calm 1100ms 的单 action 附加停顿上限。

#### Scenario: 重放相同请求
- **WHEN** 相同 seed、correlation 和世界状态再次执行表现决策
- **THEN** 产生相同 gaze/dwell trace，并且每次 dwell 为取消保留至少 2 秒 deadline 余量

### Requirement: 三级表现模式安全降级
系统 SHALL 支持 `off`、`visual_only` 和 `full`，默认 off，并 SHALL 提供只能关闭表现的全局 kill switch。

#### Scenario: off 模式
- **WHEN** presentation mode 为 off 或 kill switch 生效
- **THEN** 可靠性修复保持启用，但不记录公开活动、不执行表现动作且不生成过程旁白

#### Scenario: visual only 模式
- **WHEN** presentation mode 为 visual_only
- **THEN** 活动、视觉状态、Live2D 提示和安全头部动作启用，但不调用过程旁白 LLM 或 TTS

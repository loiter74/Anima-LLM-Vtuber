## ADDED Requirements

### Requirement: 系统持久化公开活动投影
系统 SHALL 在已持久化的任务与命令边界生成 planning、observing、committed、acting、checking、recovering 和 finished 活动，并 SHALL 使用单调 sequence、幂等 source key 和 append-only journal 保存。

#### Scenario: 成功任务按证据完成
- **WHEN** 一个任务完成 runtime action、post-observation 和独立 goal verification
- **THEN** 系统按顺序记录活动，并且仅在独立验证成功后记录 `finished/succeeded`

#### Scenario: 未知写操作进入恢复
- **WHEN** state-changing action 的结果未知且需要 reconciliation
- **THEN** 系统记录 `recovering/active`，并在持久化 reconciliation 终态前不宣告成功

### Requirement: 公开活动不得泄露内部推理和身份
系统 MUST 只公开受限的 phase、intent、focus、progress 和 outcome，并 MUST 拒绝 reasoning、工具参数、隐藏坐标、内部 command/objective/step/correlation/request/runtime 标识、hash、receipt 和证据路径。

#### Scenario: 序列化公开活动
- **WHEN** PublicActivityRecorder 收到包含私有执行字段的内部事实
- **THEN** 输出只包含规范允许的字段，focus label 来自 canonical 安全显示映射且最长 64 字符

### Requirement: 活动交付可回放且不影响执行
系统 SHALL 先提交活动再 best-effort 发布，采用 at-least-once 交付，并 SHALL 允许客户端按 event ID 和 sequence 去重；投影存储或 Socket 发布失败 MUST NOT 改变世界动作结果。

#### Scenario: 公共客户端重连
- **WHEN** public-live 客户端重新连接且没有 cursor
- **THEN** 服务端主动按 sequence 升序发送最近配置数量的安全活动，客户端合并 live/replay 时不重复显示

#### Scenario: 发布失败
- **WHEN** activity 已提交而 Socket 发布失败
- **THEN** command outcome 保持不变，活动可在后续重放中恢复

### Requirement: 原始 Minecraft 投影保持私有
系统 MUST 将包含 caller scope、request、evidence 或内部状态的原始投影限制在受信任房间，public-live principal SHALL 只能收到公开活动与叙事状态。

#### Scenario: 公开客户端尝试监听原始投影
- **WHEN** public-live 客户端连接正式服务
- **THEN** 客户端不会收到任何原始 mission/objective/command payload 或内部标识

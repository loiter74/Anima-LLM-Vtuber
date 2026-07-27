## MODIFIED Requirements

### Requirement: 表情控制
`<Live2DRenderer>` SHALL accept an optional versioned semantic performance plan with audio delivery and SHALL resolve it through the active model profile. The response LLM path SHALL NOT control raw Live2D parameters or motion indices.

#### Scenario: 音频开始时切换表情
- **WHEN** 当前任务的真实音频开始且携带有效的 cheerful performance plan
- **THEN** Live2D 模型在 250 ms 内淡入模型配置的柔和开心表情

#### Scenario: 无效计划
- **WHEN** performance plan 无效、过期或当前模型不支持
- **THEN** Live2D 模型保持平静待机且不执行原始动作

### Requirement: 口型同步
`<Live2DRenderer>` SHALL support lip sync from TTS audio and SHALL give the lip-sync layer exclusive ownership of `ParamMouthOpenY`. Facial expressions MAY control mouth form but SHALL NOT write mouth-open.

#### Scenario: TTS 音频播放时口型同步
- **WHEN** 收到当前任务的流式或完整 TTS 音频
- **THEN** Live2D 模型嘴部开合 SHALL follow the audio after model motion and performance overlays are applied

### Requirement: 自动行为
`<Live2DRenderer>` SHALL support automatic blinking, mouse focus, and a deterministic calm idle. For Hiyori, `Hiyori_m01` SHALL be the only automatic idle motion; unreviewed `m02`–`m10` motions SHALL NOT be selected automatically or by the LLM response path.

#### Scenario: 自动眨眼
- **WHEN** Live2D 模型处于空闲状态
- **THEN** 模型以随机间隔执行眨眼动画

#### Scenario: 平静待机
- **WHEN** 没有当前可播放语音
- **THEN** Hiyori SHALL remain on the looping `m01` calm sway

#### Scenario: 鼠标注视跟踪
- **WHEN** 用户在 Live2D 渲染区域内移动鼠标
- **THEN** 模型眼球跟随鼠标位置

### Requirement: 分层表演生命周期
`<Live2DRenderer>` SHALL coordinate calm, armed, speaking, and settling states. It SHALL apply model motion and physics first, performance overlays second, and lip sync last.

#### Scenario: 正常播放完成
- **WHEN** 当前语音播放结束
- **THEN** 表情 SHALL 在 350 ms 内回到平静并继续 `m01`

#### Scenario: 播放中断
- **WHEN** 当前语音被取消、断流、任务替换或连接断开
- **THEN** 控制器 SHALL cancel pending accents, close the mouth, and return safely to calm

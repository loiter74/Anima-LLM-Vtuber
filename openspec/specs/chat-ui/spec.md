## Purpose
Defines the chat interface behavior for message display, input, voice controls, and subtitle presentation.
## Requirements
### Requirement: ChatPanel 布局组件
系统 SHALL 提供 `<ChatPanel>` 组件作为聊天区域容器，包含标题栏、消息列表、输入区域。

#### Scenario: 聊天面板渲染
- **WHEN** ChatPanel 组件挂载
- **THEN** 显示连接状态指示、消息列表、底部输入栏，整体使用 glassmorphism 半透明面板风格

### Requirement: MessageList 消息列表
系统 SHALL 提供 `<MessageList>` 组件，渲染聊天消息列表，支持自动滚动到底部、流式消息更新动画。

#### Scenario: 新消息自动滚动
- **WHEN** 收到新消息
- **THEN** 列表自动滚动到底部，显示新消息入场动画

#### Scenario: 用户手动上翻后不强制滚动
- **WHEN** 用户主动上翻查看历史消息
- **THEN** 新消息到来时不强制滚动，而是显示"有新消息"提示

#### Scenario: 空状态提示
- **WHEN** 消息列表为空
- **THEN** 显示空状态占位图和引导文案

### Requirement: MessageBubble 消息气泡
系统 SHALL 提供 `<MessageBubble>` 组件，区分用户消息和 AI 回复，支持流式打字效果、时间戳显示。

#### Scenario: 用户消息气泡
- **WHEN** 渲染 role 为 `user` 的消息
- **THEN** 显示为右侧对齐的气泡，使用用户强调色背景

#### Scenario: AI 回复流式显示
- **WHEN** AI 消息处于流式接收状态
- **THEN** 文本逐字追加显示，末尾显示打字光标动画

#### Scenario: AI 回复完成
- **WHEN** AI 消息接收完毕
- **THEN** 打字光标消失，消息右下角显示完成时间

### Requirement: InputBar 输入栏
系统 SHALL 提供 `<InputBar>` 组件，包含文本输入框、发送按钮、语音按钮，支持 Enter 发送、Shift+Enter 换行。

#### Scenario: 文本输入发送
- **WHEN** 用户在输入框输入文字并按 Enter
- **THEN** 消息通过 `useChat().sendText()` 发送，输入框清空

#### Scenario: 多行输入
- **WHEN** 用户按 Shift+Enter
- **THEN** 输入框插入换行，不触发发送

#### Scenario: 输入框自动增高
- **WHEN** 输入内容超过一行
- **THEN** textarea 自动增高，最大高度限制为 120px

### Requirement: VoiceButton 语音按钮
系统 SHALL 提供 `<VoiceButton>` 组件，点击开始录音，再次点击停止，录音中显示音量指示动画。

#### Scenario: 开始录音
- **WHEN** 用户点击语音按钮
- **THEN** 按钮变为录音状态（红色脉冲动画），调用 `useVoice().startRecording()`

#### Scenario: 录音中音量反馈
- **WHEN** 录音进行中
- **THEN** 按钮下方显示音量条动画，实时反映麦克风音量

#### Scenario: 停止录音
- **WHEN** 用户再次点击语音按钮
- **THEN** 停止录音，发送音频数据，按钮恢复默认状态

### Requirement: TypingIndicator 打字指示器
系统 SHALL 提供 `<TypingIndicator>` 组件，当 AI 正在处理时显示跳动的圆点动画。

#### Scenario: AI 处理中
- **WHEN** 消息发送后等待 AI 回复
- **THEN** 消息列表底部显示三个跳动的圆点动画

### Requirement: SpeakingIndicator 说话指示器
系统 SHALL 提供 `<SpeakingIndicator>` 组件，当 TTS 音频播放时显示波形动画。

#### Scenario: TTS 播放中
- **WHEN** 后端发送 `audio` 或 `audio_with_expression` 事件
- **THEN** 显示波形动画指示器，播放结束自动隐藏

### Requirement: Subtitle translations match the active turn
The chat UI SHALL display translated subtitle text only when the translation belongs to the currently active subtitle turn.

#### Scenario: Matching translation is displayed
- **WHEN** the UI receives a `chat:sentence` event with `turn_id`
- **AND** the UI later receives a `chat:subtitle_translation` event with the same `turn_id`
- **THEN** the UI SHALL display that translation with the current original subtitle

#### Scenario: Stale translation is ignored
- **WHEN** the UI receives a `chat:subtitle_translation` event with a `turn_id` older than the current subtitle turn
- **THEN** the UI SHALL ignore that translation
- **THEN** the current original subtitle SHALL remain unchanged

#### Scenario: Translation does not replace original subtitle
- **WHEN** the UI is in bilingual subtitle mode
- **AND** a matching translation arrives
- **THEN** the UI SHALL keep the original subtitle text visible
- **THEN** the UI SHALL render the translation as the translated subtitle text

#### Scenario: Legacy translation without turn identity is safe
- **WHEN** the UI receives a translation event without `turn_id`
- **THEN** the UI SHALL NOT overwrite a newer subtitle turn
- **THEN** the UI MAY display it only when no current turn identity is known

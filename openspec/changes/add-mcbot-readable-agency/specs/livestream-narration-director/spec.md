## ADDED Requirements

### Requirement: 共享导演只使用公开事实
BroadcastNarrationDirector SHALL 只消费脱敏活动投影；full 模式下的旁白生成 MUST 禁用工具和对话记忆，并 MUST 在 2 秒内输出最长 60 字符的一句中文，否则跳过 TTS并保留确定性视觉文本。

#### Scenario: 旁白生成超时
- **WHEN** full 模式的 persona composer 在 2 秒内没有返回合法句子
- **THEN** 页面仍显示最长 80 字符的确定性活动文本，且不会提交迟到 TTS

#### Scenario: 非法内部字段
- **WHEN** director 输入包含 reasoning、原始工具参数或内部执行身份
- **THEN** director 拒绝该 cue，并且不会把字段传给 LLM、Socket 或页面

### Requirement: 媒体仲裁保护 viewer 和唱歌体验
系统 SHALL 以统一 BroadcastMediaTurn 仲裁字幕与音频，只有 stop/generation switch/emergency cancel 可以硬中断；viewer 回复高于任务旁白，唱歌持有独占 lease。

#### Scenario: viewer 回复到达时存在待播进度
- **WHEN** viewer reply 与普通任务进度 cue 同时等待媒体
- **THEN** viewer reply 先播放，旧进度在 TTL 过期后丢弃而不是延迟播报

#### Scenario: 唱歌正在进行
- **WHEN**任务活动在 singing lease 有效时到达
- **THEN**视觉状态立即更新，但任务旁白在唱歌释放 lease 前不播放

### Requirement: 旁白限频、合并并可取消
系统 SHALL 对非终态旁白使用 6 秒冷却和 15 秒 TTL，对 correction/terminal 使用 60 秒 TTL，并 SHALL 在同一 mission/objective 只保留一个待播 progress cue。

#### Scenario: 快速连续进度
- **WHEN** 同一目标在冷却期内产生多个普通进度活动
- **THEN** 新进度替换旧进度，terminal 或 correction 不会被普通进度覆盖

#### Scenario: generation 切换
- **WHEN** 直播 generation 切换或 emergency stop
- **THEN** 所有旧 cue 和旧 generation 音频被取消，后续页面状态不会恢复旧内容

### Requirement: 两张直播表面共享状态且单点播放
`/live.html` 与 `/minecraft-gameplay.html` SHALL 使用同一公开鉴权和 activity/cue/task identity，并 SHALL 通过 `media=active|muted` 保证只有 active owner 实际播放。

#### Scenario: 两页同时连接
- **WHEN** live 页面为 active 且 gameplay 页面为 muted
- **THEN** 两页显示同一活动状态，但只有 live 页的 playback count 增加

#### Scenario: OBS gameplay 成为音频 owner
- **WHEN** gameplay 页面以 `media=active` 启动且另一 browser source 停止或 muted
- **THEN** gameplay 页播放同一 chat 音频并记录匹配的 task ID、completed 状态和播放次数

### Requirement: 游戏直播页不伪造现场内容
Minecraft gameplay 页面 MUST 使用 public-live auth 和真实弹幕、字幕、活动及 TTS 事件；固定预览弹幕和默认台词 SHALL 只在 `review=1` 时出现。

#### Scenario: 正式游戏页面加载
- **WHEN** 页面未携带 `review=1`
- **THEN** 页面不显示任何固定样例弹幕或默认台词，并通过 public-live principal 只读连接

### Requirement: 实际播放证据是音频验收真值
两个页面 SHALL 持久记录 audio owner、playback count、last audio task ID 和 playback state；收到 Socket 或服务端合成成功 MUST NOT 被视为播放成功。

#### Scenario: owner 页面完成过程旁白
- **WHEN**共享播放器实际开始并完成 narration task
- **THEN** playback count 增加、last task ID 等于 cue task，最终 playback state 为 completed

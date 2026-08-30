## Context

Minecraft 任务已经通过 Voyager 控制平面完成持久化、单飞执行、动作前后观察、receipt 校验和独立目标验收，但 LLM 在提交 MissionSpec 后即退出逐步执行，正式直播只能看到最终回复。mc-mcp 还存在取消信号未覆盖全部 capability、transport timeout 不会终止底层动作和导航超时误报成功等问题；在此基础上直接加入停顿会放大拖尾风险。

本变更横跨 Python 控制平面、Node/Mineflayer runtime、Socket.IO、LangGraph 媒体交付以及两个直播页面。所有世界写操作仍必须经过 CommandExecutor，公开产品工具仍只有 `mc_connection` 和 `mc_operate_bot`。

## Goals / Non-Goals

**Goals:**

- 让观众看到可验证的规划、观察、承诺、行动、检查、恢复和终态，而不是内部思维链。
- 在不改变任务目标、路径和世界 mutation 的前提下，以真实目标注视和有界短停改善第一人称直播观感。
- 让公开活动可持久化、幂等、回放、排序和脱敏，并让投影失败与直播失败不影响游戏执行。
- 复用现有字幕、TTS、共享播放器和嘴型链路，统一 viewer、旁白、主动话题和唱歌的音频所有权。
- 以 `off / visual_only / full` 支持安全灰度和快速关闭。

**Non-Goals:**

- 不公开 chain-of-thought、prompt、工具参数、内部执行身份或隐藏坐标。
- 不随机走位、犯错、替换目标、改变 pathfinder 路径或重写战斗策略。
- 不在 v1 增加复合建造/采集 capability、新公开工具或新 Live2D 资产。

## Decisions

### 可靠性作用域先于表现层

mc-mcp 引入统一 OperationScope，向所有 capability 传播 signal、deadline、correlation、phase reporter 和清理资源。等待、导航、dig、PVP、controls 和 container 均须可取消并在 terminal 前确认静止；transport busy 只能在 operation terminal 或 quarantine 后释放。选择统一作用域而不是给每个动作打补丁，是为了保持取消与 deadline 的单一真相源。

### 私有阶段与公开活动分层

Node `action_phase` 保留 capability、correlation、target 和 attempt 等运行信息，仅在内部 event buffer 流转。Python `PublicActivityRecorder` 只在持久化边界把这些事实与 mission 状态合并为受限枚举投影。公开层不包含自由 reasoning 字段；策略仍是无副作用纯函数。

### 活动先持久化再发布

公开活动使用 command journal 内独立 append-only 表和全局单调 sequence。私有 source key 保证重试幂等，Socket 采用 at-least-once 交付，客户端按 event ID/sequence 去重。无 cursor 的公共连接只回放最后配置数量；Socket 失败不能回滚活动或 command。

### 头部优先的确定性动作表现

BroadcastMotionPolicy 仅能通过窄 PresentationPort 注视真实语义锚点和执行可取消短停。动作所有权固定为 safety、combat、final interaction aim、navigation/dig/container、presentation。表现时长由配置 seed 和 correlation 派生，不使用随机全局状态；危险、取消或 deadline 紧迫时退化为 event-only。

### 公开视觉与音频解耦

BroadcastNarrationDirector 立即发布确定性视觉状态；full 模式才将脱敏 payload 交给无记忆、禁用工具的 LangGraph 旁白子流程。生成超时或失败时保留视觉文本并跳过 TTS。真实音频继续通过既有 chat 事件，避免第二套播放器协议。

### 全局媒体仲裁

现有 viewer ReplyMediaTurn 适配为统一 BroadcastMediaTurn；仅 P0 stop/generation 切换可硬中断。唱歌获取独占 lease，viewer 回复高于任务旁白，terminal/recovery 高于普通进度。过期的非终态 cue 被丢弃而不是晚到后播报旧状态。

### 两张页面共享身份但只有一个音频 owner

`/live.html` 和 `/minecraft-gameplay.html` 消费同一 activity/cue/task identity。页面以 `media=active|muted` 决定播放权；live 默认 active，gameplay 默认 muted，OBS Minecraft scene 显式切为 active。gameplay 的预览弹幕和台词只在 `review=1` 存在。

### 原始投影不进入公开房间

当前 mission/objective 等内部 projection 改为受信任房间广播；public-live 只收到安全 activity 和 narration state。公共客户端连接时由服务端主动发送最近活动，保持 public-live 无业务上行权限。

## Risks / Trade-offs

- [旁白与动作错位] → 只向 LLM提供已提交的公开投影，2 秒超时，进度 cue 合并，过期即丢弃。
- [表现层延长取消] → 每次 dwell 预留 2 秒收敛窗口，总时长受 tempo 上限约束，危险和紧迫状态关闭表现。
- [双页面重复播放] → 显式 audio owner、同一 task identity 和持久播放证据；验收只接受 owner 页计数。
- [活动事件泄露内部数据] → 严格 Pydantic/TypeScript schema、extra forbid、canonical label 映射和递归隐私测试。
- [Socket 重放重复] → commit-first、单调 sequence、source-key 幂等、客户端 live/replay 合并去重。
- [媒体仲裁改动回归 viewer 顺序] → 保留现有 ReplyMediaTurn source order，在其外层接入全局 arbiter并复用既有回归测试。

## Migration Plan

1. 先部署 OperationScope、取消/超时修复和私有投影隔离，配置保持 off。
2. 部署 activity journal、公开投影和页面消费，以 visual_only 在固定世界验收。
3. 启用头部动作并比较 off/visual_only 的世界结果和时延。
4. 部署导演和媒体仲裁，使用 full 验证真实宿主 TTS 与两个页面。
5. 仅在完整门禁通过后将正式直播 profile 设为 full；出现问题可用 kill switch 立即退回 off，可靠性修复继续保留。

## Open Questions

无。v1 的范围、模式、默认值、音频所有权和验收阈值均已确定。

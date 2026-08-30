## Why

Animetta 当前会在后台可靠地观察、执行和验证 Minecraft 任务，但正式直播只能看到粗粒度动作和最终回复，观众无法理解角色注意到了什么、正在尝试什么以及为何修正。需要把真实、可验证的行动阶段投影为直播可读的 AI 主体性，同时不牺牲现有预算、幂等、取消和世界状态校验。

## What Changes

- 增加持久化、可回放且经过脱敏的 Minecraft 公开活动投影，表达规划、观察、承诺、行动、检查、恢复和终态。
- 为 mc-mcp 增加可取消、受 deadline 约束的统一操作作用域，并修复超时后底层动作继续运行、导航误报成功和预算/错误详情丢失问题。
- 增加只塑造视线与短暂停顿的确定性直播动作策略；它不得改变目标、路径、方块、背包或战斗决策。
- 增加共享直播叙事导演，将公开活动转换为确定性视觉状态，并在 full 模式下生成受限的一句式人格旁白。
- 统一 viewer 回复、任务旁白、主动话题和唱歌的媒体仲裁，真实字幕与音频继续使用现有 chat 事件和共享播放器。
- 同时接入 `/live.html` 与 `/minecraft-gameplay.html`，为游戏页补齐 public-live 鉴权、真实事件、评审夹具隔离和单一音频 owner。
- 增加 `off`、`visual_only`、`full` 三档配置和只能强制关闭的紧急开关；默认关闭，正式直播验收后显式开启。
- 将原始 Minecraft 内部投影限制在受信任房间，公开客户端只接收脱敏投影和叙事状态。

## Capabilities

### New Capabilities

- `minecraft-public-activity`: 定义可验证、持久化、可回放且不泄露内部推理或执行身份的公开活动投影。
- `minecraft-broadcast-presentation`: 定义可靠性前置条件、三档模式和安全、确定性的头部动作表现。
- `livestream-narration-director`: 定义共享叙事、媒体仲裁、两张直播表面和实际播放证据。

### Modified Capabilities

无。

## Impact

- Python Minecraft 控制平面、SQLite command journal、Socket.IO Minecraft 路由和配置契约。
- 独立 mc-mcp runtime、GameBot v2 capability adapter、动作阶段事件与 Mineflayer 表现策略。
- LangGraph 叙事生成、现有回复媒体协调、TTS 交付链路和 Socket 事件目录。
- `/live.html` 与 `/minecraft-gameplay.html` 的公开客户端、字幕、Live2D、音频 owner 和浏览器证据。
- 新增契约、单元、集成、浏览器和真实运行验收；公开产品工具仍严格只有 `mc_connection` 与 `mc_operate_bot`。

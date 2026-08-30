---
name: review-anima-live
description: 打开、显示或评审 Animetta 真实直播页面，执行演示前确认的轻量真实验收，并在明确要求时完成 OBS、发布矩阵、Live2D 性能、TTS 故障转移和真实 Bilibili 数据评审。用户要求打开真实直播、检查直播界面、真实演示、视觉回归、Live2D 表现或音频故障转移时使用。
---

# 评审 Animetta 直播

复用统一 review CLI 声明的 feature 路由和通用 Playwright 规则，不从 Vue Router 推断直播入口。

## 模式

- **display**：用户只要求打开、显示或获取直播页面时，运行
  `pnpm --silent -C frontend run review -- --feature <id> --base-url <当前前端源> --print-url`，再用用户指定或当前浏览器打开其唯一输出。不得启动 OBS、评审浏览器或写评审证据。
- **review**：用户要求检查、截图、OBS、视觉、音频或性能证据时，执行下述对应强度的评审流程。

## 验收强度

- **smoke（默认）**：用户未明确要求发布、production、完整矩阵或全能力覆盖时，只执行一个代表性真实场景一次。演示前请求一次确认；确认覆盖已列明的准备、执行、证据采集和收尾。只采集动作、表现、收尾三类证据。
- **release**：只有用户明确要求发布、production、完整矩阵、全能力覆盖或启用正式 `full` 时才进入。按受影响范围执行必要矩阵，不把所有历史场景机械套到每次验收。

## 流程

1. 读取 `frontend/AGENTS.md`，按 [features.md](references/features.md) 选择唯一 feature，并确定 `display`、`smoke` 或 `release`。
2. display 只解析并打开 CLI 返回的规范 URL；不得读取前端路由器、启动 OBS 或使用兼容重定向入口。
3. review 在启动运行时前完成一次有界只读预检：确认产品调用路径存在、场景能产生目标证据、动作影响和预算可界定、收尾可恢复。smoke 用一句话向用户说明“演示场景、实际动作、最大影响、收尾方式”并等待一次确认；任一条件不成立就停止，不启动运行时，也不替换成旁路探针。
4. 确认后，请求若包含启动、停止或恢复 Animetta，先交给 `$operate-anima-runtime`；运行时 ready 后完成已确认的后台动作。需要浏览器证据时加载 `$qa-testing-playwright`，并只运行一次 `pnpm -C frontend run review -- --feature <id>`，不得为同一场景启动重复浏览器。
5. smoke 只执行已确认的一个真实场景一次，并并行采集三类证据：
   - **动作**：结果、预算和相关 receipt；
   - **表现**：目标页面上的事件、状态或画面；
   - **收尾**：恢复预期模式和运行时健康。
   只有场景涉及世界修改、取消或音频时，才分别增加相关前后状态、静止收敛或真实播放证据。首次失败立即停止，不自动重试、不改走其他 capability；诊断和下一次演示分开，下一次仍需用户确认。
6. release 只执行本次受影响的必要矩阵。背景、层级、缩放或位置变更先用 `--no-obs` 做一次目标视口诊断，并同时确认资源加载、Live2D 不遮挡面板、弹幕标题与正文不被模型覆盖；稳定 OBS 评审再使用专用场景和 Browser Source。`--no-obs` 不得冒充 OBS 稳定证据。
7. 使用真实 Bilibili 数据时调用项目 Bilibili MCP 控制现有会话，不直接启动 `DanmakuService` 或第二条网关连接。只根据本轮新证据判断通过或失败。
8. 验收真实 TTS 播放时，触发前记录 `#audioStatus[data-playback-count]`；触发后必须同时证明计数递增、`data-last-audio-task-id` 等于本轮 `task_id`、最终 `data-playback-state` 为 `playing` 或 `completed`，且控制台没有播放失败。合成成功或收到事件不能替代真实播放证据。

## 计时

- 每次 review 都从本轮 `summary.json` 的 `started_at` 与 `finished_at` 计算 `duration_seconds`；评审在生成 summary 前失败或中断时改用 `run.json` 的同名字段。沿用现有 evidence，不新增计时台账或手工秒表。
- 计时记录同时携带 `feature_id`、`profile`、`workflow_fingerprint` 和 `status`。存在相同 `workflow_fingerprint` 的上一轮时，报告上一轮耗时、本轮耗时和差值；没有可比记录时标注为首次基线。
- 旧记录只用于迭代耗时比较，不参与本轮功能、视觉或播放通过判定。未显式设置性能阈值时，耗时变长只报告，不自动判失败。

## 不变量

- 保留 `text-boundaries` 与 `sparse` 的名称、消息、弹幕文案和精确断言；只能新增场景，不得替换这些固定夹具。
- 不复用旧截图、旧控制台或旧健康证据。
- 不把页面加载成功当成视觉、音频或 Live2D 行为通过。
- 不通过修改评审夹具来掩盖产品回归。
- 真实直播事件可能包含未脱敏身份；只在当前评审需要时读取，不另行持久化。

## 报告

报告 feature、验收强度、已确认场景、动作/表现/收尾证据、结论、失败点和本轮耗时；有相同 workflow fingerprint 的历史记录时附耗时差。release 另报告页面与 OBS 来源，并明确区分浏览器诊断与稳定评审。

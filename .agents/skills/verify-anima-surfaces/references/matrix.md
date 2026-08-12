# 双页面验收矩阵

| 入口 / 工作区 | 最小真实验收 | 自动测试边界 |
| --- | --- | --- |
| `/dashboard` 现场 | 四个任务可切换；开发者输入形成真实回合；检查器显示非 mock LLM | 路由只保留 Dashboard；命令身份与 developer metadata |
| `/dashboard` 节目 / 脚本 | 列表加载；草稿、校验、发布和节目控制至少完成一条可逆链路 | Repository、API、Run 与 Replay 契约 |
| `/dashboard` 节目 / 唱歌 | 地址校验；启动、取消/错误或完成态；完成态音轨与字幕入口 | Store、Socket 事件和组件状态 |
| `/dashboard` 节目 / Meme | 加载/空载/错误；手动添加或审核一条候选 | Socket 回调、过滤和状态归属 |
| `/dashboard` 记忆 | 加载、筛选、详情；固定/修正/发送沙盒至少一条可逆链路 | Store 与 Socket CRUD、发送草稿不自动提交 |
| `/dashboard` 验证 / 沙盒 | 非 mock Provider 回复；可中断；无字幕、TTS、记忆提交 | 独立事件、History-neutral LLM 服务、无 LangGraph 调用 |
| `/dashboard` 验证 / 重放 | 脚本或 JSONL 启动；暂停、继续、单步、调速和停止 | Coordinator 状态机与 API 契约 |
| `/live.html` | 页面加载；字幕 DOM；Live2D；公开回复；TTS 播放计数与 task_id | 唯一入口、Socket 绑定、播放状态持久证据 |

所有浏览器项同时检查控制台错误、失败请求、关键横向溢出和指定视口。涉及外部写入或高成本真实服务时，只执行用户授权且可恢复的最小动作。

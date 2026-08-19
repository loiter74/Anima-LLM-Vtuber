# ANIMETTA — 根目录智能体指南

Animetta 是 AI 伙伴与虚拟主播框架。后端使用 Python 3.13、Starlette（不是 FastAPI）、LangGraph 和 Socket.IO ASGI；前端使用 Vue 3、Electron 和 Live2D。

本文件只定义全仓库规则。修改具体目录前，必须读取距离目标文件最近的 `AGENTS.md`。

## 项目地图

| 任务              | 主要位置                                                     |
| --------------- | -------------------------------------------------------- |
| LLM / ASR / TTS | `src/animetta/services/{llm,asr,tts}/`                   |
| LangGraph 节点    | `src/animetta/orchestration/graph/`                      |
| Socket.IO 路由    | `src/animetta/orchestration/server/routes.py`            |
| 产品工具 / MCP 客户端  | `src/animetta/tools/`                                    |
| 开发智能体 MCP       | `tooling/<能力>_mcp/`                                      |
| 人格              | `config/personas/`、`src/animetta/config/persona/`        |
| 记忆              | `src/animetta/memory/v2/`                                |
| Live2D          | `src/animetta/avatar/`、`frontend/src/components/live2d/` |
| 歌唱              | `src/animetta/services/singing/`                         |
| Minecraft       | `src/animetta/tools/minecraft/`                          |
| 架构决策            | `docs/adrs/`                                             |

## 智能体配置

项目规则只保存在根目录/分目录 `AGENTS.md` 和 `.agents/skills/`。不得新增 `CLAUDE.md`、`.claude/`、`.opencode/`、`.wolf/`、`.understand-anything/` 等其他智能体专用规则。

`.zcode/` 只保存本地计划和会话数据，不作为项目规则来源，也不纳入版本控制。

新增或修改项目 Skill、开发智能体 MCP 时：

* Skill 正文、`agents/openai.yaml`、MCP 服务说明、工具描述和用户可见消息使用中文；
* 目录名、工具名、协议字段、`error_code` 保持英文；
* 代码符号和日志遵循所在目录规则。

## 后端约束

### Python

使用 Python 3.13+；Windows 项目命令必须使用 `py -3.13`。

读取中文 Skill、夹具或配置的独立 Python 工具子进程必须设置 `PYTHONUTF8=1`，不得修改全局编码环境。

验证前执行 `py -3.13 -c "import sys; assert sys.version_info >= (3, 13)"`；不可用时停止，不得回退。使用现代类型标注、Pydantic V2 `ConfigDict`、异步 I/O、公共函数类型标注和英文 `loguru` 日志。

### 编排

LangGraph 是唯一编排方式。不得重新引入 EventBus、已删除的 `pipeline/`、`events/`、`handlers/`、`adapters/`、旧版 `core/`、`services/conversation/` 或旧版 `state/`。状态图节点保持轻量，业务逻辑放入 `services/` 或对应领域模块。

### ServicePool

不得对 `ServicePool` 调用 `ctx.close()`，否则会销毁共享引擎。

### Provider

LLM / ASR / TTS Provider 遵循 `interface.py → implementation → factory → __init__.py export`，并使用现有 `@ProviderRegistry`。新增实现前先确认可复用的 Provider、服务或扩展点。

## 记忆

当前记忆实现位于 `src/animetta/memory/v2/`，遵循 ADR-005；不得恢复或绕过旧记忆路径。

## 产品工具与开发工具

产品运行时工具放在 `src/animetta/tools/`，开发智能体 MCP 放在 `tooling/<能力>_mcp/`。开发 MCP 不得注册到 `config/tools.yaml` 或进入产品运行时依赖。

## Minecraft

`src/animetta/tools/minecraft/` 是位于 Python 仓库中的 Node.js 项目。

修改前读取该目录自己的 `AGENTS.md`，不要套用普通 Python 模块规则。

## 前端与 Live2D

前端修改遵循 `frontend/AGENTS.md`、`STYLE_GUIDE.md` 和 `design-system/`，优先复用 Vue 组件与 UnoCSS 模式，不得新增原始颜色值或网络字体。Live2D 实时缩放使用缓存的 `baseBounds`，不得调用 `getBounds()`。

### 设计系统

只读取当前任务需要的规格：

| 需求        | 文件                                                |
| --------- | ------------------------------------------------- |
| 品牌与语气     | `design-system/brand.html`                        |
| 颜色        | `design-system/colors.html`                       |
| 字体        | `design-system/typography.html`                   |
| 间距 / 动效   | `design-system/spacing.html`                      |
| 组件        | `design-system/components.html`                   |
| UI 组合     | `design-system/ui-kit.html`                       |
| UnoCSS 映射 | `design-system/USAGE.md`、`frontend/uno.config.ts` |

硬性规则：

* 使用 UnoCSS 设计令牌，不直接写原始颜色；
* 玻璃层级保持 `bg → surface → panel → card`；
* 默认圆角 `rounded-xl`；
* 动效时长只使用 150 / 200 / 300ms；
* 缓动使用 `ease-out-expo` 或 `ease-back-soft`。

新增设计令牌时同时更新 `design-system/colors_and_type.css` 和 `frontend/uno.config.ts`；新增真正的公共组件模式时更新 `components.html`。

## 运行时与 Docker

日常源码修改不启动 Docker。仅当用户明确要求启动/运行/发布，或改动 Docker/Compose、运行生命周期、端口、启动协议及其他高风险运行时行为时进入运行时验证。

用户点名真实访问 URL 或要求当前运行实例体现改动时，必须把该 URL 作为最终验收对象：先确认其实际服务进程和前端资源指纹，再通过规范生命周期更新运行时，并在同一 URL 验证结果。Vite 开发或预览端口只能证明源码构建，不能证明真实入口已更新。

Qwen TTS 仅作为 Windows 宿主机服务运行在 `127.0.0.1:8767`；不得恢复 Qwen Dockerfile、Compose service 或容器生命周期。RVC 唱歌声线推理仅运行在宿主机 `127.0.0.1:8769`；不得新增 RVC Compose service 或把 GPU 推理依赖装入主容器。

### GPU 密集型任务

模型训练、批量推理、长音频分离/转换等持续 GPU 任务启动前必须：

* 用 `nvidia-smi` 记录 GPU 型号、`memory.total`、`memory.used`、`memory.free`，并核对计算进程 PID 与完整命令行；总显存不得当作可用显存，无法确认进程归属时停止；
* 保证同类任务只有一个实例；停止或重启前必须终止目标进程树并复核精确命令行已消失，外层终端、包装脚本退出或 `Ctrl+C` 不构成停止证据；
* 长任务开始前检查同一工作区的其他活动任务不会执行 `anima-up`、`host-tts-up` 或 `host-rvc-up`；运行中若出现新的生命周期进程，先停止本次长任务并协调触发源，不得与另一任务反复争抢启停宿主服务；
* 先用保守 batch 执行有界峰值探针并持续采样显存，只有实测峰值仍保留 `max(总显存的 25%, 6 GiB)` 空闲时才可开始长任务；不满足时降低 batch、精度或任务规模后重新探针；
* 不得仅因启动前空闲显存看似充足就提高 batch；每次提高都必须重新执行峰值探针。长任务使用可恢复检查点，并在显存预算越界时终止目标进程树。

生命周期统一通过 `py -3.13 scripts/runtime_lifecycle.py` 执行。`anima-down` 必须保留宿主机 Qwen 与 RVC；只有 `host-tts-stop`、`host-rvc-stop` 可分别停止它们。

LangGraph Redis checkpointer 依赖 RediSearch 与 RedisJSON。Redis 8 官方镜像通过 `docker-entrypoint.sh redis-server` 自动加载捆绑模块；Compose 使用 shell 展开密码时必须重新进入该官方入口，不能直接从 shell 启动 `redis-server`。变更 Redis 版本或启动方式时，必须同时验证 `FT.CREATE`、`JSON.SET` 和官方 `AsyncRedisSaver` 索引初始化，不能只以 `PING` 判定可用。

## 已删除入口

不得恢复或引用 `scripts/start.py`、`--mode`、`--no-app`。

## 测试与验证

修改过程中优先运行最相关的目标测试。最终差异冻结后，运行一次影响感知验证：

```powershell
py -3.13 -m tooling.quality verify --tier affected --paths <本次任务路径...> --cache read-write
```

组件映射只定义在 `tooling/quality.yml`，不得手工绕过规划器要求的测试组。仅修改质量模型、该文件或目录映射时先运行 `py -3.13 -m tooling.quality validate`。

仅修改 `AGENTS.md` 或不参与产品、测试、发布契约的内部 Markdown 时，冻结差异后只运行 `git diff --check -- <文件...>`；提交时以仓库提交钩子为最终检查，不运行 Python、affected 或 Playwright。其他文档、普通单测和 Skill 验证也不得启动 Playwright；仅界面行为、E2E 或浏览器证据变化时使用浏览器测试。

### 执行时间预算

普通修改默认在 10 分钟内完成：定位与约束 2 分钟、实现 5 分钟、简化与验证 3 分钟。

* 定位优先使用 CodeGraph 和精确路径，不做无目标的全仓扫描或重复读取；
* 使用 `apply_patch` 落地大型多文件成果时，先分离旧文件替换与新文件创建；包含旧上下文匹配的修改不得与大量新文件捆成一个原子补丁，避免单点失配回滚整批；
* 默认不启动子 Agent、Docker、Playwright、full、发布门禁、基准测试或依赖安装；
* 目标测试或 quick 仅用于诊断；最终按上述规则验证一次，不重复已覆盖测试；
* 预计超时就停止扩大范围，及时报告结果、阻塞和最短下一步；只有用户明确要求的运行时、E2E、发布、基准测试或大型改造可超时。

## 修改边界

保留工作区中与当前任务无关的修改。

不得修改 `data/`、`memory_db/` 中的运行时数据或自动生成的 `artifacts/`、`evidence/`。除非用户明确要求替换文案，不得修改直播评审 `text-boundaries`、`sparse` 夹具的名称、消息、弹幕文案或精确断言。

修改前确认现有接口和项目模式；仅在业务规则不明确且会改变行为时询问用户。

## Simplify 与调试

实际修改后对最终实现执行一次 `simplify`，只降低任务相关复杂度，不承担通用提交前检查。

出现缺陷、失败或非预期行为时使用 `systematic-debugging`：稳定复现 → 调用链/数据流 → 根因 → 修复 → 验证；不得连续堆叠症状补丁。

### 执行效率反思

出现重复失败、错误路径、重复搜索/验证或明显超出预期成本时，在结束前调用 `efficiency-retrospective`；正常短任务不调用。反思不得扩大任务范围，可重复结论固化到最近的 `AGENTS.md`、已有 Skill、确定性脚本或质量映射。

## Git

完成用户要求且验证通过后，默认自动提交本任务修改并安全推送 `origin/main`，无需等待额外指令；用户明确要求不提交或不推送时除外。禁止使用破坏混合工作区的 `git clean`、`git reset --hard`、`git checkout --`。

普通推送采用单次远端刷新路径：确认 `status` / 目标差异 → `fetch origin main` 一次并验证可快进 → 精确暂存 → 提交 → `push origin main`。提交后不得为同一推送重复 fetch；若远端随后变化，由普通 push 的非快进拒绝安全终止并报告。

对混合行尾文件做部分暂存或构造 blob 时，用 Python 二进制读写生成目标内容，再 `git hash-object -w --no-filters` + `git update-index --cacheinfo` 入库；不得用 sed 管道改写 blob，也不得信任 MSYS 管道（`sed` / `od` / `cat -A`）显示的行尾。

若无法安全隔离当前任务、远端 `main` 已变化、无法快进、分支受保护或推送失败，停止并报告，不得强推。

## 架构图

架构图使用 `json-canvas` Skill，保存到 `C:\Users\30262\Documents\my-llm-wiki\my-llm-wiki\Excalidraw\{项目名}\`。

约定：

* 项目总览放项目根目录；
* 子决策放对应子目录；
* 节点间距至少 50px；
* 分组内边距至少 20px；
* 文本节点宽度 200–300px，不低于 150px；
* 所有关系添加标签。

颜色：

* `1`：关键
* `3`：警告 / 依赖
* `4`：完成 / 新增
* `5`：标题 / 信息
* `6`：可选 / 高级

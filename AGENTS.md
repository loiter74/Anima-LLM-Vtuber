# ANIMETTA — 根目录智能体指南

Animetta 是一个 AI 伙伴与虚拟主播框架：后端使用 Python 3.13、**Starlette + LangGraph + Socket.IO ASGI**（不是 FastAPI），前端使用 Vue 3、Electron 和 Live2D。

本文件只记录全仓库规则。修改具体目录前，先阅读距离目标文件最近的 `AGENTS.md`：

- 后端：[src/animetta](src/animetta/AGENTS.md)、[核心](src/animetta/core/AGENTS.md)、[编排](src/animetta/orchestration/AGENTS.md)、[状态图](src/animetta/orchestration/graph/AGENTS.md)、[服务](src/animetta/services/AGENTS.md)、[记忆](src/animetta/memory/AGENTS.md)、[配置](src/animetta/config/AGENTS.md)、[工具](src/animetta/tools/AGENTS.md)、[Minecraft](src/animetta/tools/minecraft/AGENTS.md)、[虚拟形象](src/animetta/avatar/AGENTS.md)、[巡检](src/animetta/inspection/AGENTS.md)
- 其他区域：[前端](frontend/AGENTS.md)、[测试](tests/AGENTS.md)、[评估](evaluations/AGENTS.md)、[架构决策记录](docs/adrs/AGENTS.md)

## 智能体配置

- 仓库只保留 Codex 与 ZCode 共用的根目录/分目录 `AGENTS.md`，以及 Codex 使用的 `.agents/skills/`；不得新增 `CLAUDE.md`、`.claude/`、`.opencode/`、`.wolf/`、`.understand-anything/` 或其他智能体专用配置。
- Codex 按作用域读取最近的 `AGENTS.md`。ZCode 先读取根目录 `AGENTS.md`，修改具体目录前还必须主动读取距离目标文件最近的分目录 `AGENTS.md`，确保两者遵循同一套规则。
- `.zcode/` 只保存本地计划和会话数据，不纳入版本控制，也不作为项目规则来源。

## 修改位置

| 任务 | 主要位置 |
|---|---|
| LLM、ASR、TTS 提供方 | `src/animetta/services/{llm,asr,tts}/` |
| LangGraph 节点或 Socket.IO 路由 | `src/animetta/orchestration/graph/`、`src/animetta/orchestration/server/routes.py` |
| 工具或 MCP 集成 | `src/animetta/tools/` |
| 人格 | `config/personas/`、`src/animetta/config/persona/` |
| 记忆行为 | `src/animetta/memory/v2/`（ADR-005） |
| Live2D | `src/animetta/avatar/`、`frontend/src/components/live2d/` |
| 歌唱 | `src/animetta/services/singing/` |
| Minecraft 机器人 | `src/animetta/tools/minecraft/`（Python 目录中的 Node.js 项目） |
| 架构决策 | `docs/adrs/` |

## 不可违反的约定

- 使用 **Python 3.13+**。在 Windows 上运行测试、质量门禁、脚本或本地后端命令时，必须使用 `py -3.13`，不得使用裸 `python`。验证前先运行 `py -3.13 -c "import sys; assert sys.version_info >= (3, 13)"`；如果不可用，立即停止。
- Windows 命令按 PowerShell 语义执行：一次工具调用只运行一个有意义的命令；相互独立的只读检查由调用层并行，不使用 `;` 拼接。`rg` 的字面正则优先用单引号包裹，避免 PowerShell 对双引号和反斜杠进行二次解释。
- 使用现代类型标注（`X | None`）、Pydantic V2 `ConfigDict`、异步 I/O、公共函数类型标注和英文 `loguru` 日志。
- 保持状态图节点轻量；复用 `services/` 中的业务逻辑。提供方遵循 `interface.py` → 实现 → 工厂 → `__init__.py` 导出的结构，并使用 `@ProviderRegistry`。
- 修改前核实接口和现有模式。业务规则不明确时先确认；优先复用现有抽象，添加有意义的测试，并分步修改。
- 前端工作遵循 `STYLE_GUIDE.md`、`frontend/AGENTS.md` 和设计系统规格。使用 UnoCSS 令牌，不得使用原始颜色值。
- 保留工作区中与当前任务无关的修改。不得手工编辑生成的 `artifacts/`、`evidence/`，也不得编辑 `data/` 和 `memory_db/` 中的运行时数据。
- 除非用户明确要求替换文案，否则保留直播评审目录中 `text-boundaries` 和 `sparse` 夹具的名称、消息、弹幕文案及精确断言。

## 必须执行的工作流

### Git 提交与远程推送

- 每次修改完成并通过适用验证后，无需再次询问用户：先清理本次任务产生的临时文件和一次性产物，再检查工作区，然后自动提交并推送主干。这里的“清理工作区”仅限当前任务明确产生且可安全删除的内容；不得使用 `git clean`、`git reset --hard`、`git checkout --`，不得删除、覆盖、暂存或提交与当前任务无关的修改。
- 允许在本地使用临时任务分支，但不得把个人分支、任务分支或任何非 `main` 分支推送到远程。
- 远程推送只能以 `origin/main` 为目标。完成任务后，先在本地把任务提交合并或快进到 `main`，确认提交范围和验证结果，再推送主干。
- 混合工作区只能暂存当前任务的文件；切换分支、合并和推送时必须保留无关的未提交修改。
- 自动提交前，先用 `git diff --check -- <本次任务路径...>` 检查未暂存差异并只暂存当前任务文件；暂存后以 `git diff --cached --check`、`git diff --cached --name-status` 和 `git status --short` 为最终范围证据。全工作区检查若只命中无关用户改动，不得修改该文件来消除失败。提交信息必须准确描述本次修改。若无法安全隔离当前任务、主干不是可快进状态、远程主干已前进、分支受保护或推送失败，立即停止，不得强推，并向用户报告阻塞原因。
- `main` 推送成功后，删除已经合并的本地临时分支。若远程已经存在任务分支，确认其提交已进入 `main` 后删除该远程分支。

### 修改后反思

- 每完成一批源代码、测试、构建或运行脚本、含代码配置的修改后，必须在最终验证与交付前调用 `reflect-code-changes`，无需等待用户提醒。
- 后续再次修改代码时必须重新调用，包括验证过程中产生的修复。本技能自身的整理改动属于同一次调用，只需检查最终差异一次，不得递归调用。
- 反思与整理仅限当前任务涉及的路径。

### 调试

- 遇到缺陷、失败或非预期行为时，使用 `systematic-debugging`。
- 先稳定复现，再追踪完整调用链和数据流，检查配置与初始化顺序，必要时在边界添加诊断。修复根因，不得只处理下游症状。
- 两次修复失败后停止叠加补丁并重新检查假设；三次失败后必须先讨论架构，再尝试下一次修改。

### 质量保证与影响感知验证

- 开始任何测试或质量保证阶段时，使用 `qa-testing-playwright` 规划最小充分验证。纯文档或治理规则变更不因此启动浏览器；仅在界面行为发生变化或质量规划器选择浏览器组时采集页面证据。浏览器或界面证据必须来自全新的页面捕获，不得复用以前的 Playwright 结果。
- Windows 不得先探测或尝试 `make`：直接使用 `py -3.13 -m tooling.quality validate`、`py -3.13 -m tooling.quality verify --tier quick --worktree --cache read-write`、`py -3.13 -m tooling.quality verify --tier affected --worktree --cache read-write`。POSIX 环境可使用对应的 `make quality-validate`、`make test-quick`、`make test-affected`；完整门禁及基准命令见 `tests/AGENTS.md`。
- 验证按成本递增：完成计划内修改并调用 `reflect-code-changes`；运行目标测试、格式/静态检查、文档不变量和 `quality validate`；只暂存本次任务文件后运行 `py -3.13 -m pre_commit run`，并核对暂存差异；最后运行一次规划器选择的 `affected`/`full` 门禁。新增外部模型、音频或其他二进制资产时，必须在昂贵门禁前完成许可证、清单引用、文件大小和大文件钩子检查。不得用 `--no-verify` 绕过失败。
- 若廉价检查或反思导致源代码、测试、构建/运行脚本或含代码配置再次变化，从反思与廉价检查重新开始；不要在仍有已知待修问题时反复启动昂贵门禁或 Docker 构建。
- `tooling/quality.yml` 是唯一的组件到测试映射。验证测试组必须由机器自动选择，由规划器根据改动路径、影响闭包、风险、层级和能力决定；不得手工跳过必需测试组，也不得复制选择逻辑。覆盖支配关系只有在该文件中声明时才有效，每个省略项都必须记录在冻结计划中。
- 只有带有精确可信指纹且成功的可缓存密闭结果才允许复用。完整、夜间和发布门禁必须使用 `cache off`。
- Playwright 和实时服务测试组始终重新采集页面、健康状态、就绪状态、请求、控制台、截图和日志证据。冻结计划与结果保存到 `artifacts/test-impact/`。

### 修改代码后的 Docker 启动协议

不得在主智能体中启动后端。必须使用专用子智能体，并在任一步进入终态失败时立即停止。子智能体应在每个协议步骤结束时汇报，长时间构建至少每 60 秒给出一次进度；主智能体不得因等待而另起一套重复生命周期。服务就绪以 HTTP 成功响应为准，不得以进程退出或容器状态代替。

1. 运行 `py -3.13 scripts/runtime_lifecycle.py host-tts-up`；要求 `127.0.0.1:8767/health`、带鉴权的 `/ready` 和精确模型身份均通过。
2. 运行 `py -3.13 scripts/runtime_lifecycle.py anima-down`；确认宿主机 Qwen 仍然就绪。
3. 运行 `py -3.13 scripts/runtime_lifecycle.py anima-up`。CPU 或冒烟验证通过当前 PowerShell 进程设置 `ANIMETTA_PROFILE=smoke`，并复用同一个 `docker-compose.yml`。该命令为有界续跑：若返回 `status=in_progress`（通常 exit 2），这不是失败；从输出读取 `run_id`，使用相同 profile 运行 `py -3.13 scripts/runtime_lifecycle.py --run-id <同一值> anima-up`，直到 `passed` 或 `failed`。同一租约存活时不得创建新的 `anima-up` run。
4. 每 5 秒轮询一次 `http://localhost/health`，最多 120 秒；要求 HTTP 200 且响应包含 `"status":"ok"`。
5. 每 5 秒轮询一次 `http://localhost`，最多 60 秒；要求 HTTP 200。
6. 检查默认 Compose 应用日志和本次宿主机 Qwen 证据；不得出现回溯或错误级别日志。
7. 只有全部检查通过后，才能报告 `[OK] 宿主机 Qwen 已就绪，Docker 容器健康，前端可通过 80 端口访问`。

Qwen 只能作为 Windows 宿主机服务运行在 `127.0.0.1:8767`；不得恢复 Qwen Dockerfile、Compose 服务、容器或容器生命周期命令。`anima-down` 必须保留该服务，只有 `host-tts-stop` 可以释放它。

## 架构约束

- 不得导入已删除的 `pipeline/`、`events/`、`handlers/`、`adapters/`、旧版 `core/`、`services/conversation/` 或旧版 `state/` 模块。
- LangGraph 是唯一编排方式；不得重新引入 EventBus（ADR-001）。
- 不得对 `ServicePool` 调用 `ctx.close()`，否则会销毁共享引擎。
- 不得把业务逻辑写入状态图节点。
- Live2D 缩放不得实时调用 `getBounds()`；使用缓存的 `baseBounds`，定位规则见 `frontend/AGENTS.md`。
- `scripts/start.py`、`--mode` 和 `--no-app` 已删除，不得恢复或引用。

## 界面与设计系统

设计系统 HTML 文件是规格说明，不是运行时页面。只读取当前任务需要的文件：

| 需求 | 规格文件 |
|---|---|
| 品牌、语气、标识 | `design-system/brand.html` |
| 颜色、字体、间距、动效 | `design-system/colors.html`、`design-system/typography.html`、`design-system/spacing.html` |
| 组件模式 | `design-system/components.html` |
| 应用外壳与组合方式 | `design-system/ui-kit.html` |
| UnoCSS 映射 | `design-system/USAGE.md`、`frontend/uno.config.ts` |

硬性规则：

- 不得自行增加颜色或网络字体。角色语气只用于消息内容，系统语气只用于徽标、胶囊标签和提示消息。
- 保持玻璃面板层级 `bg → surface → panel → card`；需要进一步区分时使用边框或光晕，不得增加第五种明度。
- 默认使用 `rounded-xl`（12px）。动效时长只能使用 150、200 或 300ms，缓动使用 `ease-out-expo` 或 `ease-back-soft`。
- 新组件应复用最接近的 Vue 和 UnoCSS 既有模式。真正的新组件需要记录到 `components.html`。
- 新令牌必须同时添加到 `design-system/colors_and_type.css` 和 `frontend/uno.config.ts`，并记录其用途。

## 架构图

- 使用 `json-canvas` 技能，将 `.canvas` 文件保存到 `C:\Users\30262\Documents\my-llm-wiki\my-llm-wiki\Excalidraw\{项目名}\`。
- 项目总览放在项目根目录，子决策放入各自的子目录。
- 使用带标签的分组；节点间距至少 50px，分组内边距至少 20px，文本节点宽度为 200–300px，且不得低于 150px。
- 统一颜色含义：`1` 表示关键，`3` 表示警告或依赖，`4` 表示完成或新增，`5` 表示标题或信息，`6` 表示可选或高级。
- 为关系添加标签。必要说明应作为节点放在图旁，不得作为独立段落放在图下方。

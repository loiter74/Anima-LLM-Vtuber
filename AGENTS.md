# ANIMETTA — 根目录智能体指南

Animetta 是 AI 伙伴与虚拟主播框架。

技术栈：

* 后端：Python 3.13、Starlette、LangGraph、Socket.IO ASGI
* 前端：Vue 3、Electron、Live2D
* 编排：LangGraph
* 后端框架是 **Starlette，不是 FastAPI**

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

主要分目录规则：

* `src/animetta/AGENTS.md`
* `src/animetta/core/AGENTS.md`
* `src/animetta/orchestration/AGENTS.md`
* `src/animetta/orchestration/graph/AGENTS.md`
* `src/animetta/services/AGENTS.md`
* `src/animetta/memory/AGENTS.md`
* `src/animetta/config/AGENTS.md`
* `src/animetta/tools/AGENTS.md`
* `src/animetta/tools/minecraft/AGENTS.md`
* `src/animetta/avatar/AGENTS.md`
* `src/animetta/inspection/AGENTS.md`
* `frontend/AGENTS.md`
* `tests/AGENTS.md`
* `evaluations/AGENTS.md`
* `docs/adrs/AGENTS.md`

## 智能体配置

项目规则只保存在：

* 根目录和分目录 `AGENTS.md`
* Codex 使用的 `.agents/skills/`

不得新增其他智能体专用规则目录或文件，例如：

* `CLAUDE.md`
* `.claude/`
* `.opencode/`
* `.wolf/`
* `.understand-anything/`

`.zcode/` 只保存本地计划和会话数据，不作为项目规则来源，也不纳入版本控制。

新增或修改项目 Skill、开发智能体 MCP 时：

* Skill 正文、`agents/openai.yaml`、MCP 服务说明、工具描述和用户可见消息使用中文；
* 目录名、工具名、协议字段、`error_code` 保持英文；
* 代码符号和日志遵循所在目录规则。

## 后端约束

### Python

使用 Python 3.13+。

Windows 上运行项目 Python 命令必须使用：

```powershell
py -3.13
```

读取中文 Skill、夹具或配置的独立 Python 工具子进程必须设置 `PYTHONUTF8=1`，不得修改全局编码环境。

验证前先执行：

```powershell
py -3.13 -c "import sys; assert sys.version_info >= (3, 13)"
```

不可用时停止，不得退回其他 Python 版本。

使用：

* `X | None` 等现代类型标注；
* Pydantic V2 `ConfigDict`；
* 异步 I/O；
* 公共函数类型标注；
* 英文 `loguru` 日志。

### 编排

LangGraph 是唯一编排方式。

不得重新引入：

* EventBus；
* 已删除的 `pipeline/`；
* `events/`；
* `handlers/`；
* `adapters/`；
* 旧版 `core/`；
* `services/conversation/`；
* 旧版 `state/`。

状态图节点保持轻量。

业务逻辑放入 `services/` 或对应领域模块，不得堆入图节点。

### ServicePool

不得对 `ServicePool` 调用：

```python
ctx.close()
```

否则会销毁共享引擎。

### Provider

LLM / ASR / TTS 等 Provider 遵循现有结构：

```text
interface.py
→ implementation
→ factory
→ __init__.py export
```

并使用现有 `@ProviderRegistry` 机制。

新增实现前先确认是否已有可复用 Provider、服务或扩展点。

## 记忆

当前记忆实现位于：

```text
src/animetta/memory/v2/
```

遵循 ADR-005。

不得恢复或绕过已经淘汰的旧记忆路径。

## 产品工具与开发工具

产品运行时工具放在：

```text
src/animetta/tools/
```

开发智能体使用的 MCP 服务放在：

```text
tooling/<能力>_mcp/
```

开发 MCP 不得注册进产品：

```text
config/tools.yaml
```

避免把开发期工具引入产品运行时依赖。

## Minecraft

`src/animetta/tools/minecraft/` 是位于 Python 仓库中的 Node.js 项目。

修改前读取该目录自己的 `AGENTS.md`，不要套用普通 Python 模块规则。

## 前端与 Live2D

前端修改遵循：

* `frontend/AGENTS.md`
* `STYLE_GUIDE.md`
* `design-system/`

优先使用已有 Vue 组件和 UnoCSS 模式。

不得直接增加原始颜色值或网络字体。

Live2D 实时缩放不得调用：

```text
getBounds()
```

必须使用缓存的 `baseBounds`。

具体定位规则见 `frontend/AGENTS.md`。

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

新增设计令牌时必须同时更新：

* `design-system/colors_and_type.css`
* `frontend/uno.config.ts`

新增真正的公共组件模式时更新 `components.html`。

## 运行时与 Docker

日常源码修改不自动启动 Docker。

只有以下情况进入运行时验证：

* 用户明确要求启动、运行或发布；
* 修改 Docker / Compose；
* 修改运行生命周期；
* 修改端口或启动协议；
* 其他直接影响运行时环境的高风险变更。

Qwen TTS 只能作为 Windows 宿主机服务运行在：

```text
127.0.0.1:8767
```

不得恢复：

* Qwen Dockerfile；
* Qwen Compose service；
* Qwen 容器生命周期。

RVC 唱歌声线推理只能作为 Windows 宿主机服务运行在：

```text
127.0.0.1:8769
```

不得新增 RVC Compose service 或把 GPU 推理依赖装入 Animetta 主容器。

标准生命周期统一通过：

```powershell
py -3.13 scripts/runtime_lifecycle.py
```

执行。

`anima-down` 必须保留宿主机 Qwen 与 RVC。

只有各自的 `host-tts-stop`、`host-rvc-stop` 可以停止它们。

## 已删除入口

不得恢复或引用：

* `scripts/start.py`
* `--mode`
* `--no-app`

## 测试与验证

修改过程中优先运行最相关的目标测试。

最终差异冻结后，以仓库质量规划器作为最终影响感知验证：

```powershell
py -3.13 -m tooling.quality verify --tier affected --paths <本次任务路径...> --cache read-write
```

组件到测试的映射只定义在：

```text
tooling/quality.yml
```

不要手工绕过规划器要求的测试组。

只有修改质量模型、`tooling/quality.yml` 或目录映射时才运行：

```powershell
py -3.13 -m tooling.quality validate
```

普通单测、文档和 Skill 验证不得启动 Playwright。

只有界面行为、E2E 或浏览器证据发生变化时使用浏览器测试。

`artifacts/` 和 `evidence/` 中的生成内容不得手工修改。

### 执行时间预算

普通源码、测试、配置和文档修改默认在 10 分钟内完成，按“定位与约束 2 分钟、实现 5 分钟、简化与 affected 验证 3 分钟”时间盒执行。

* 定位优先使用 CodeGraph 和精确路径，不做无目标的全仓扫描或重复读取；
* 默认不启动子 Agent、Docker、Playwright、full、发布门禁、基准测试或依赖安装；
* 最终只运行一次精确文件列表的 affected 验证；目标测试或 quick 仅用于诊断，已被 affected 覆盖时不得重复；
* 预计无法在 10 分钟内完成时，必须在超时前停止扩大范围并报告已完成结果、剩余阻塞和最短下一步，不得静默继续；只有用户明确要求的运行时、E2E、发布、基准测试或大型改造可以超出该预算。

## 修改边界

保留工作区中与当前任务无关的修改。

不得修改：

* `data/` 中运行时数据；
* `memory_db/` 中运行时数据；
* 自动生成的 `artifacts/`；
* 自动生成的 `evidence/`。

除非用户明确要求替换文案，不得修改直播评审中 `text-boundaries` 和 `sparse` 夹具的：

* 名称；
* 消息；
* 弹幕文案；
* 精确断言。

修改前确认现有接口和项目模式。

业务规则不明确且会改变行为时再询问用户。

## Simplify 与调试

完成实际修改后，对最终实现执行一次 `simplify`。

Simplify 只负责降低当前任务相关结构的复杂度，不承担通用提交前检查。

出现缺陷、失败或非预期行为时使用 `systematic-debugging`：

```text
稳定复现
→ 调用链 / 数据流
→ 根因
→ 修复
→ 验证
```

不得连续堆叠症状补丁。

### 执行效率反思

出现重复失败、明显错误路径、重复搜索、重复验证或本轮执行明显超出预期成本时，在任务结束前调用 `efficiency-retrospective`。

正常直接完成的任务不调用。

反思只用于减少未来相似任务的时间和 token 消耗；不得借此扩大当前任务范围。可重复结论按性质固化到最近的 `AGENTS.md`、已有 Skill、确定性脚本或质量映射中。

## Git

最终验证通过后，只提交当前任务产生的修改。

禁止使用破坏混合工作区的命令，例如：

```text
git clean
git reset --hard
git checkout --
```

推送目标只能是：

```text
origin/main
```

普通推送采用单次远端刷新路径：确认 `status` / 目标差异 → `fetch origin main` 一次并验证可快进 → 精确暂存 → 提交 → `push origin main`。提交后不得为同一推送重复 fetch；若远端随后变化，由普通 push 的非快进拒绝安全终止并报告。

若无法安全隔离当前任务、远端 `main` 已变化、无法快进、分支受保护或推送失败，停止并报告，不得强推。

## 架构图

架构图使用 `json-canvas` Skill。

保存到：

```text
C:\Users\30262\Documents\my-llm-wiki\my-llm-wiki\Excalidraw\{项目名}\
```

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

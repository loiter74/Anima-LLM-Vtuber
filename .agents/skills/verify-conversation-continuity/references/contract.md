# 连续性回归维护契约

## 权威来源

| 责任 | 权威入口 |
| --- | --- |
| 状态转移与脱敏 evidence | `src/animetta/acceptance/conversation_continuity.py` |
| 跨入口确定性场景 | `tests/acceptance/test_livestream_conversation_continuity.py` |
| Provider 显式历史闭包 | `tests/services/llm/test_explicit_history_contract.py` |
| finalizer 提交矩阵 | `tests/orchestration/graph/test_dialogue_nodes.py` |
| 正式运行时哨兵 | `scripts/conversation_continuity_canary.py` |
| 发布 evidence 校验 | `scripts/release_runtime_gate.py` |
| 测试选择与支配关系 | `tooling/quality.yml` |

这些文件中的可执行定义优先于本文。本文只规定维护闭包，不复述状态计数、Provider 清单或提交原因。

## 模式选择

| 请求 | 模式 | 行为 |
| --- | --- | --- |
| 普通实现、诊断或本地回归 | `deterministic` | 通过质量计划运行聚焦契约；禁止网络和 Docker |
| 明确要求当前正式实例或正式 URL | `runtime` | 先运行 `deterministic`，再执行正式 canary 并严格校验脱敏 evidence |
| `full`、`nightly` 或发布门禁 | 现有 release gate | CI 直接运行，不通过 Skill 包装器转发 |

`runtime` 不授予服务生命周期权限。实例未就绪时，只在用户已授权运行时操作的前提下交给 `$operate-anima-runtime`。

## 只生成计划时的固定输出

用户要求只生成计划且提供四个字段时，`deterministic` 必须逐字使用：

```text
模式: deterministic
入口: py -3.13 .agents/skills/verify-conversation-continuity/scripts/run_regression.py --mode deterministic
最终门禁: $validate-anima affected
禁止: 网络, Docker, runtime canary, backend-full
```

用户要求只生成计划且提供五个字段时，`runtime` 必须逐字使用，并把 `<正式URL>` 替换为用户指定的 URL：

```text
模式: runtime
入口: py -3.13 .agents/skills/verify-conversation-continuity/scripts/run_regression.py --mode runtime --url <正式URL>
顺序: deterministic -> canary -> evidence validator
证据: 仅脱敏字段
生命周期: 未就绪且已授权时交给 $operate-anima-runtime
```

## 维护闭包

| 变化 | 必须同步扩展 |
| --- | --- |
| 新聊天入口或来源 | 跨入口 acceptance 场景、作用域隔离和来源断言 |
| 新 LLM Provider | Factory 目录适配器、显式历史与流式合同 |
| 新 finalizer 提交或排除条件 | 带稳定 pytest ID 的提交资格矩阵 |
| replay probe 默认行为 | replay dispatcher 聚焦测试和跨入口场景 |
| 连续性 trace 或 evidence 字段 | 产品契约、canary 假边界和 release validator 测试 |
| 连续性实现路径变化 | 质量组件路径、代表路径和 full dominance 测试 |
| Skill 模式或脚本行为变化 | `tests/agent_skills/` 单测与固定 Skill 回归用例 |

新增项必须闭合相应矩阵；不得只增加实现而依赖开发者临时挑选测试。

## 隐私与夹具边界

- evidence 只允许保存 trace ID、作用域、窗口计数、布尔判据和稳定错误码。
- 输入、回答、历史正文、随机公开暗号、私密标记和工具载荷只能在进程内比较。
- 观测和 Skill 输出不得新增对话正文。
- 不复用、不改名、不改写 `text-boundaries`、`sparse` 直播评审夹具及其精确断言。

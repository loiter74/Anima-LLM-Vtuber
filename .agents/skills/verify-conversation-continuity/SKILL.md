---
name: verify-conversation-continuity
description: 固化并执行 Animetta Dashboard 与直播弹幕的短期对话连续性回归。修改聊天入口、LLM Provider 显式历史、finalizer 提交资格、replay probe、连续性 trace、运行时 canary 或 release evidence，或要求验证正式实例连续性时使用。
---

# 验证直播对话连续性

让产品契约和质量目录保持权威；只在这里固化模式选择、执行顺序和报告边界。

## 流程

1. 完整读取 [contract.md](references/contract.md)，确认改动命中哪一项维护闭包。
2. 选择且只选择一种模式：
   - 默认使用 `deterministic`；不得访问网络或启动 Docker。
   - 只有用户明确要求真实实例、正式 URL 或发布验收时使用 `runtime`。
3. 在 Windows 首次运行前断言 Python 3.13；不可用时立即停止。
4. 通过固定入口执行：

   ```powershell
   py -3.13 .agents/skills/verify-conversation-continuity/scripts/run_regression.py --mode deterministic
   py -3.13 .agents/skills/verify-conversation-continuity/scripts/run_regression.py --mode runtime --url <正式URL>
   ```

5. 若任务修改了文件，聚焦回归只作为实现期诊断；差异冻结后必须使用 `$validate-anima`，把本任务精确文件列表传给唯一 affected 门禁。
6. 只报告模式、组 ID、状态、耗时、脱敏 evidence 路径和稳定错误码。

## 运行时边界

- `runtime` 固定先运行确定性契约，再复用正式 canary 和 release evidence validator。
- 不自行启动、停止、重启或修复服务。若正式实例未就绪且用户授权更新运行时，交给 `$operate-anima-runtime`；未授权时停止并报告。
- 不直接调用 `docker compose`，不接受 Mock Provider、非 production-ready 实例或不完整 evidence。
- `full` 与 `nightly` 继续直接运行 release gate；不得改成依赖本 Skill 被触发。

## 约束

- 不把 pytest 目标、状态转移或 evidence schema 复制进 Skill 脚本；从 `tooling.quality.yml` 和产品 validator 读取。
- 不保存或报告用户输入、模型回答、随机哨兵、私密标记、历史正文或工具载荷。
- 不修改或复用 `text-boundaries`、`sparse` 直播评审夹具。
- 不把聚焦回归写成第二套 affected、full 或发布门禁。

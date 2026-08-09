---
name: test-skill-regression
description: 使用仓库固定用例高效回归 Codex Skill，预检基线并验证重复执行的路径、内容、任务边界以及必须包含或禁止出现的语义。创建、重命名或修改 Skill，排查 Skill 不稳定、错误路由、越界修改或重复执行过慢时使用。
---

# Skill 回归测试

只测试目标 Skill；先确定性预检，再并行执行，最后一次性比较。

## 固定用例

每个用例位于 `fixtures/cases/`，并固定：

- `skill`、`task`、`baseline` 与 `run_count`；
- `allowed_paths` 与 `require_content_identical`；
- `invariants[].contains`：每次结果必须包含的片段；
- `invariants[].not_contains`：每次结果禁止出现的片段。

至少声明一种语义片段。执行后不得放宽路径、删除约束或修改任务来迁就结果。

## 快路径

1. 读取目标 Skill 与固定用例。
2. 运行准备器。它在创建副本前验证用例、基线和正反语义约束，然后输出唯一 `task`、`output_root` 和全部 `run_roots`：

   ```powershell
   py -3.13 .agents/skills/test-skill-regression/scripts/prepare_case.py --case .agents/skills/test-skill-regression/fixtures/cases/<case>.json
   ```

3. 把同一个 `task` 同时交给 `run_count` 个相互隔离的执行上下文；每个上下文只接收目标 Skill、自己的 `run_root` 和任务，不得读取其他运行。多个用例复用已完成的同一组执行上下文，并同时触发下一批，避免串行等待或重新占用槽位。
4. 全部完成后只运行一次高层比较；它直接读取隔离目录，自动检查路径、字节一致性、`contains` 和 `not_contains`：

   ```powershell
   py -3.13 .agents/skills/test-skill-regression/scripts/compare_runs.py --case .agents/skills/test-skill-regression/fixtures/cases/<case>.json --prepared-root <output_root>
   ```

5. 只有比较失败且需要检查哈希细节时，才使用 `snapshot_tree.py` 和 `compare_runs.py --baseline ...` 兼容模式；不得把低层模式作为默认流程。

## 性能约束

- 有可用槽位时一次并行启动全部运行，不逐个等待。
- 在启动执行前解决基线或禁用词失败；不得先跑完再修改用例并整批重跑。
- 单次执行超过 2 分钟时停止增加新用例，先收紧任务或 Skill；超过 5 分钟时中断并返工。
- 最终差异冻结后只运行一次影响感知质量门禁；其已覆盖的目标测试不重复执行。

## 判定与报告

通过必须同时满足：每次运行确实产生修改、修改路径集合一致、没有越出 `allowed_paths`、需要时受影响文件逐字节一致、所有正反语义约束通过。

只报告用例与次数、每次耗时、重复性、路径边界、语义约束和结论。

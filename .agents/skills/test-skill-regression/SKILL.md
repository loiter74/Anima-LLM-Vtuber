---
name: test-skill-regression
description: 使用仓库内固定用例回归测试 Codex Skill，验证相同基线上的重复执行结果、修改路径、任务边界和语义不变量。创建、重命名或修改 Skill 后使用；Skill 疑似不稳定，或需要确认它会持续检查或编辑预期路径时也使用。
---

# Skill 回归测试

只测试目标 Skill，不测试周边仓库。

## 固定用例

每个目标 Skill 必须绑定一个提交到仓库的固定用例，保存于 `fixtures/cases/`。用例固定以下内容：

- `skill`：目标 Skill 名称；
- `task`：每次执行完全相同的任务；
- `baseline`：不可变基线目录；
- `run_count`：重复次数，默认使用 `3`；
- `allowed_paths`：唯一允许改变的相对路径模式；
- `require_content_identical`：是否要求受影响文件逐字节一致；
- `invariants`：每次执行都必须保留的语义不变量。

执行前选定用例。不得在看到运行结果后放宽路径、删除不变量或修改任务；用例变化必须作为单独改动审阅。

## 流程

1. 读取目标 Skill 和它的固定用例（这些用例由skill的主要功能组成），确认用例中的 Skill 名称、基线和不变量仍有效。
2. 从同一个基线建立相互隔离的副本；任何一次执行都不得看到其他执行的文件或结论。
3. 在每个副本中独立执行完全相同的 `task`。只有副本确实隔离时才可并行。
4. 用 [snapshot_tree.py](scripts/snapshot_tree.py) 为固定基线和每次执行结果生成清单。
5. 用 [compare_runs.py](scripts/compare_runs.py) 读取固定用例并比较所有清单。
6. 逐次检查用例声明的语义不变量；哈希比较不能替代语义检查。
7. 性能迭代，如果发现skill执行过程中执行时间大于2min，需要调整缩短，大于5min，需要返工检查性能。

Windows 必须使用 Python 3.13：

```powershell
py -3.13 .agents/skills/test-skill-regression/scripts/snapshot_tree.py <固定基线目录> <baseline.json>
py -3.13 .agents/skills/test-skill-regression/scripts/compare_runs.py --case .agents/skills/test-skill-regression/fixtures/cases/<skill>.json --baseline <baseline.json> <run1.json> <run2.json> <run3.json>
```

比较脚本必须收到与用例 `run_count` 完全相同的运行清单；允许路径和逐字节一致性只能来自用例，不接受临时命令行覆盖。

## 判定

- **路径一致性**：每次新增、修改和删除的相对路径集合相同。
- **边界一致性**：没有修改超出 `allowed_paths`。
- **用例稳定性**：任务、基线、约束和判定标准在本轮执行前已经固定。

路径集合不同即为回归，除非固定用例本身明确允许多个目标。一个固定用例足以作为冒烟回归；只有出现实质不同的执行路径时才增加新用例。

## 报告

只报告：

- **用例**：固定用例标识和重复次数；
- **重复性**：逐字节或语义结果是否一致；
- **路径与边界**：修改路径是否一致且未越界；
- **结论**：通过或失败，以及最小的具体差异。
- **性能**：每次执行的时间，是否超过阈值。
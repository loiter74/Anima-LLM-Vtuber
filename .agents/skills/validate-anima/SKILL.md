---
name: validate-anima
description: 为 Animetta 改动选择并运行最小且完整的影响感知验证。修改源代码、测试、Skill、配置或文档后需要测试、静态检查、质量门禁、失败诊断或发布验证时使用。
---

# 验证 Animetta

让 `tooling.quality` 成为测试选择的唯一真相源，避免重复门禁。

## 流程

1. 读取目标文件附近的 `AGENTS.md`，列出本次任务实际修改的精确文件路径；传给 `--paths` 的每一项必须是文件，不得传目录。
2. 在 Windows 首次验证前运行 Python 3.13 断言；不可用时立即停止。
3. 按 [commands.md](references/commands.md) 选择日常、诊断或发布通道。
4. 最终差异冻结后，只运行所选通道的一条规范入口。规划器已经覆盖的目标测试不得重复运行。
5. 若计划出现未知路径、错误命中 Docker 或日常改动选择 `backend-full`，停止执行并修正质量映射。
6. 报告冻结计划、选中组、缓存来源、耗时和失败证据；不得把未执行项写成通过。

## 约束

- 日常通道固定使用 affected，并传入当前任务的精确文件路径，不得用目录代替。
- `quick` 只用于定位，不能与最终 affected 串行重复。
- `quality validate` 只用于质量目录、模型或映射结构变更。
- `full`、shadow、benchmark 和实时 Docker 只用于对应的高风险或发布需求。
- 文档、普通单测和 Skill 验证不加载 Playwright；界面或浏览器证据变化时才使用 `$qa-testing-playwright`。
- 格式化、换行或生成元数据等语义不变修正，只复跑对应检查。

## 输出

只给出验证结论、实际运行命令、选中测试组、耗时和最小失败信息。

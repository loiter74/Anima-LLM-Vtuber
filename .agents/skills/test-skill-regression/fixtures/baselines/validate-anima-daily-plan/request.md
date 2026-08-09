# 固定请求

改动路径只有 `.agents/skills/demo/SKILL.md`，属于日常指导 Markdown 修改。

将 `result/plan.md` 精确写成以下三行：

```text
通道: affected
命令: py -3.13 -m tooling.quality verify --tier affected --paths .agents/skills/demo/SKILL.md --cache read-write
禁止: quick, backend-full, live-docker
```

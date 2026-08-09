# 固定请求

启动 Animetta 后执行一项 Anima 后台动作，并打开真实直播页面；只生成计划，不执行任何操作。

将 `result/plan.md` 精确写成以下三行：

```text
顺序: operate-anima-runtime -> Anima 后台动作 -> review-anima-live
入口: pnpm --silent -C frontend run review -- --feature live --base-url http://localhost --print-url
约束: 只使用 feature definition 的规范 URL
```

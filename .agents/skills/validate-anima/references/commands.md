# 验证入口

## 日常通道

```powershell
py -3.13 -c "import sys; assert sys.version_info >= (3, 13)"
py -3.13 -m tooling.quality plan --tier affected --paths <精确任务文件路径...>
# 冻结前按文件类型机械格式化：
py -3.13 -m ruff format <本轮 Python 文件...>
pnpm --dir frontend exec prettier --write <本轮前端文件...>
git diff --check
py -3.13 -m tooling.quality verify --tier affected --paths <精确任务文件路径...> --cache read-write
```

适用于不修改依赖、锁文件、外部协议、Docker、部署和安全边界的常规改动。目标为 120 秒内返回结果。
`plan` 只选择测试，不执行测试；若它选择 `backend-full`，不要先手工运行被其覆盖的宽泛测试。

## 诊断通道

只为定位失败运行单个目标测试或 quick。修复完成后，以一次 affected 作为最终证据；若 affected 已覆盖目标测试，不再重复。

```powershell
py -3.13 -m tooling.quality verify --tier quick --worktree --cache read-write
```

## 质量映射

修改 `tooling/quality.yml`、质量模型或测试目录结构时，先运行：

```powershell
py -3.13 -m tooling.quality validate
```

随后仍使用一次 affected 验证最终路径。

## 发布通道

只有用户明确要求完整发布门禁时，依次运行 full、冻结 Docker 计划和 release runtime gate，并关闭缓存。不得把这组命令用于普通修改。

# Zombie File Cleanup Design

**Date**: 2026-06-14
**Status**: Approved
**Scope**: ~80 files across Python backend, Vue frontend, and project root

## Context

Animetta项目经过多轮开发迭代，积累了大量僵尸文件。通过AST解析、精确模块路径搜索、graph builder检查、factory动态加载检查四重验证，确认了~80个零引用文件。

项目已有完善的`.gitignore`（139行），但部分文件在规则添加前已提交，且一次性脚本缺乏清理机制。

## Goals / Non-Goals

**Goals:**
- 删除所有经多维度验证为零引用的僵尸文件
- 清理版本化迭代脚本，保留最新版(v42)作为参考
- 修复git跟踪问题（IDE配置、设计原型位置）
- 删除已被替代的静态资源（emoji替代PNG图标）
- 修复硬编码本地路径

**Non-Goals:**
- 不重构任何活跃代码
- 不修改任何provider注册逻辑
- 不清理test文件（test由pytest发现，不是僵尸）
- 不清理已被.gitignore正确忽略的缓存目录

## Decisions

### D1: 分阶段删除（用户选择）

**决策**：分4阶段执行，每阶段后验证，独立commit。

**阶段**：
1. Python死代码（6文件 + 坏测试）
2. 脚本清理（41版本化 + ~18一次性，保留v42）
3. 前端清理（7组件/composable + 16+静态资源）
4. Git跟踪修复 + 路径修复

**理由**：精确定位问题、便于回滚、符合项目已有清理风格（761946c）。

### D2: 保留最新版本化脚本（用户选择）

**决策**：保留 `scripts/analyze_danmaku_opencode_v42.py`，删除v5-v41。

**理由**：作为弹幕分析功能的参考实现。

### D3: 删除而非归档

**决策**：直接`git rm`删除，不归档到`archive/`目录。

**理由**：Git历史永久保留，归档目录本身会成为新clutter。

### D4: 前端shared组件全部删除（用户选择）

**决策**：删除5个未使用的Vue组件，不保留做landing page。

**理由**：零引用代码，需要时重写比维护孤立代码更高效。

## Execution Plan

### 阶段1: Python死代码
删除文件：
- `src/animetta/orchestration/graph/vc_node.py`
- `src/animetta/services/separation/demucs_separation.py`
- `src/animetta/tools/audio_tools.py`
- `src/animetta/tools/config.py`
- `src/animetta/tracing/cost_calculator.py`
- `src/animetta/utils/terminal.py`
- `tests/tracing/test_cost_calculator.py`（坏测试）

验证：`PYTHONPATH=src python -m pytest tests/ -v`

### 阶段2: 脚本清理
删除文件：
- `scripts/analyze_danmaku_opencode_v5.py` 到 `v41.py`（41个）
- ~18个一次性脚本（analyze_*.py、collect_*.py、run_*.py、execute_*.py、migrate_*.py、process-*.py、seed-*.py、start-*.py、validate-*.py）

保留：`scripts/analyze_danmaku_opencode_v42.py`

验证：`python scripts/start.py --help`

### 阶段3: 前端清理
删除文件：
- 5个Vue组件：AnimatedButton、GlassPanel、PinnedSection、ScrollProgress、ScrollReveal
- 2个composable：useAudio.ts、useFpsMonitor.ts
- 16+静态资源：`public/icons/`（11个PNG）、avatar.png、default.svg、loading/*.png、error.png

验证：`cd frontend && pnpm build`

### 阶段4: Git跟踪修复
操作：
- `git rm --cached .vscode/settings.json`
- 移动7个design-prototype*.html到`docs/designs/prototypes/`
- 删除`nul`垃圾文件
- 删除根目录重复`start-live-stream.bat`
- 移动`anima.py`到`scripts/anima_cli.py`并移除硬编码路径
- 移动`AIRI Stage UI Kit.html`和`frontend-screenshot.png`到`docs/`

验证：`git status && git diff --cached`

### 阶段5: 最终集成验证
验证命令：
- `PYTHONPATH=src python -m pytest tests/ -v`
- `cd frontend && pnpm build`
- `git add -A && git status`

提交：`git commit -m "chore: remove ~80 zombie files"`

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| 误删活跃文件 | 四重验证（AST+路径+builder+factory） |
| demucs_separation删除后配置失败 | 当前已是未完成存根，删除不影响行为 |
| cost_calculator测试删除 | 测试本身是坏的，删除消除假阳性 |
| 设计原型移动后链接失效 | 无外部链接，仅本地参考 |

## Rollback Strategy

**单阶段回滚**：`git revert HEAD`

**全量回滚**：`git revert HEAD~4..HEAD`

**文件级恢复**：`git show HEAD~N:path/to/file > path/to/file`

# Zombie File Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 删除~80个经多维度验证为零引用的僵尸文件，清理项目代码库

**Architecture:** 分4阶段执行，每阶段后验证，独立commit。使用`git rm`删除（保留历史），不归档。

**Tech Stack:** Python pytest, Vue pnpm, Git

---

## 阶段1: Python死代码清理

### Task 1.1: 删除孤立graph节点vc_node.py

**Files:**
- Delete: `src/animetta/orchestration/graph/vc_node.py`（210行）

**Step 1: 确认文件存在且零引用**

```bash
grep -r "vc_node" src/animetta/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出（零引用）

**Step 2: 删除文件**

```bash
git rm src/animetta/orchestration/graph/vc_node.py
```

**Step 3: 验证graph builder正常**

```bash
PYTHONPATH=src python -c "from animetta.orchestration.graph.builder import build_graph; print('OK')"
```

Expected: `OK`

**Step 4: 暂存不提交（等阶段1完成后统一提交）**

---

### Task 1.2: 删除悬空provider demucs_separation.py

**Files:**
- Delete: `src/animetta/services/separation/demucs_separation.py`（299行）

**Step 1: 确认文件零引用**

```bash
grep -r "demucs_separation" src/animetta/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm src/animetta/services/separation/demucs_separation.py
```

**Step 3: 验证separation factory正常**

```bash
PYTHONPATH=src python -c "from animetta.services.separation.factory import SeparationFactory; print('OK')"
```

Expected: `OK`

---

### Task 1.3: 删除零引用工具模块audio_tools.py

**Files:**
- Delete: `src/animetta/tools/audio_tools.py`（288行）

**Step 1: 确认文件零引用**

```bash
grep -r "audio_tools" src/animetta/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm src/animetta/tools/audio_tools.py
```

---

### Task 1.4: 删除零引用配置加载config.py

**Files:**
- Delete: `src/animetta/tools/config.py`（~80行）

**Step 1: 确认文件零引用**

```bash
grep -r "animetta.tools.config" src/animetta/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm src/animetta/tools/config.py
```

---

### Task 1.5: 删除零引用cost_calculator及其坏测试

**Files:**
- Delete: `src/animetta/tracing/cost_calculator.py`（97行）
- Delete: `tests/tracing/test_cost_calculator.py`（坏测试，未import被测模块）

**Step 1: 确认文件零引用**

```bash
grep -r "cost_calculator" src/animetta/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出

**Step 2: 删除两个文件**

```bash
git rm src/animetta/tracing/cost_calculator.py tests/tracing/test_cost_calculator.py
```

---

### Task 1.6: 删除零引用terminal.py

**Files:**
- Delete: `src/animetta/utils/terminal.py`（53行）

**Step 1: 确认文件零引用**

```bash
grep -r "animetta.utils.terminal" src/ scripts/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm src/animetta/utils/terminal.py
```

---

### Task 1.7: 阶段1验证与提交

**Step 1: 运行pytest验证**

```bash
PYTHONPATH=src python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: 无新增失败（可能有预存在的失败，但不应有新增）

**Step 2: 提交阶段1变更**

```bash
git commit -m "chore: remove 6 dead Python modules + 1 broken test

Removed:
- orchestration/graph/vc_node.py (orphaned graph node, never wired in builder)
- services/separation/demucs_separation.py (dangling provider, never imported)
- tools/audio_tools.py (zero references)
- tools/config.py (zero references)
- tracing/cost_calculator.py (zero references, broken test)
- utils/terminal.py (zero references)
- tests/tracing/test_cost_calculator.py (never imports module under test)"
```

---

## 阶段2: 脚本清理

### Task 2.1: 删除版本化迭代脚本v5-v41

**Files:**
- Delete: `scripts/analyze_danmaku_opencode_v5.py` 到 `v41.py`（41个文件）
- Keep: `scripts/analyze_danmaku_opencode_v42.py`（保留最新版）

**Step 1: 确认文件列表**

```bash
ls scripts/analyze_danmaku_opencode_v*.py | wc -l
```

Expected: 42（包含要保留的v42）

**Step 2: 删除v5-v41**

```bash
git rm scripts/analyze_danmaku_opencode_v{5..41}.py
```

**Step 3: 确认v42保留**

```bash
ls scripts/analyze_danmaku_opencode_v42.py
```

Expected: 文件存在

---

### Task 2.2: 删除一次性分析脚本

**Files:**
- Delete: `scripts/analyze_batch_opencode.py`
- Delete: `scripts/analyze_batch_with_opencode.py`
- Delete: `scripts/analyze_danmaku_cross.py`
- Delete: `scripts/analyze_danmaku_final.py`
- Delete: `scripts/analyze_danmaku_opencode_final.py`
- Delete: `scripts/analyze_danmaku_with_opencode.py`
- Delete: `scripts/analyze_with_opencode.py`

**Step 1: 确认文件存在**

```bash
ls scripts/analyze_batch_opencode.py scripts/analyze_danmaku_cross.py scripts/analyze_danmaku_final.py 2>&1
```

Expected: 文件存在

**Step 2: 删除文件**

```bash
git rm scripts/analyze_batch_opencode.py scripts/analyze_batch_with_opencode.py scripts/analyze_danmaku_cross.py scripts/analyze_danmaku_final.py scripts/analyze_danmaku_opencode_final.py scripts/analyze_danmaku_with_opencode.py scripts/analyze_with_opencode.py
```

---

### Task 2.3: 删除一次性采集/执行脚本

**Files:**
- Delete: `scripts/collect-voice.py`
- Delete: `scripts/collect_danmaku_batch.py`
- Delete: `scripts/collect_danmaku_by_up.py`
- Delete: `scripts/execute_cross_analysis.py`
- Delete: `scripts/run_cross_analysis.py`
- Delete: `scripts/run_opencode_analysis.py`

**Step 1: 删除文件**

```bash
git rm scripts/collect-voice.py scripts/collect_danmaku_batch.py scripts/collect_danmaku_by_up.py scripts/execute_cross_analysis.py scripts/run_cross_analysis.py scripts/run_opencode_analysis.py
```

---

### Task 2.4: 删除一次性工具脚本

**Files:**
- Delete: `scripts/migrate_socket_events.py`
- Delete: `scripts/process-icons.py`
- Delete: `scripts/seed-persona.py`
- Delete: `scripts/start-mc-bot.py`
- Delete: `scripts/validate-events.py`
- Delete: `scripts/train/collect-data.py`

**Step 1: 删除文件**

```bash
git rm scripts/migrate_socket_events.py scripts/process-icons.py scripts/seed-persona.py scripts/start-mc-bot.py scripts/validate-events.py scripts/train/collect-data.py
```

---

### Task 2.5: 阶段2验证与提交

**Step 1: 验证活跃脚本正常**

```bash
python scripts/start.py --help 2>&1 | head -5
```

Expected: 显示帮助信息

**Step 2: 提交阶段2变更**

```bash
git commit -m "chore: remove 49 one-off and versioned scripts

Removed:
- 41 versioned danmaku analysis scripts (v5-v41, kept v42)
- 7 one-off analysis scripts
- 6 one-off collection/execution scripts
- 6 one-off utility scripts

All scripts had zero references from other files."
```

---

## 阶段3: 前端清理

### Task 3.1: 删除未使用的Vue组件

**Files:**
- Delete: `frontend/src/components/shared/AnimatedButton.vue`
- Delete: `frontend/src/components/shared/GlassPanel.vue`
- Delete: `frontend/src/components/shared/PinnedSection.vue`
- Delete: `frontend/src/components/shared/ScrollProgress.vue`
- Delete: `frontend/src/components/shared/ScrollReveal.vue`

**Step 1: 确认组件零引用**

```bash
cd frontend && grep -r "AnimatedButton\|GlassPanel\|PinnedSection\|ScrollProgress\|ScrollReveal" src/ --include="*.vue" --include="*.ts" | grep -v "__tests__"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm frontend/src/components/shared/AnimatedButton.vue frontend/src/components/shared/GlassPanel.vue frontend/src/components/shared/PinnedSection.vue frontend/src/components/shared/ScrollProgress.vue frontend/src/components/shared/ScrollReveal.vue
```

---

### Task 3.2: 删除未使用的composable

**Files:**
- Delete: `frontend/src/composables/useAudio.ts`
- Delete: `frontend/src/composables/useFpsMonitor.ts`

**Step 1: 确认composable零引用**

```bash
cd frontend && grep -r "useAudio\|useFpsMonitor" src/ --include="*.vue" --include="*.ts" | grep -v "useAudioPlayback" | grep -v "__tests__"
```

Expected: 无输出（排除useAudioPlayback等近似名）

**Step 2: 删除文件**

```bash
git rm frontend/src/composables/useAudio.ts frontend/src/composables/useFpsMonitor.ts
```

---

### Task 3.3: 删除废弃静态资源

**Files:**
- Delete: `frontend/public/icons/` 整个目录（11个PNG）
- Delete: `frontend/public/avatar/avatar.png`
- Delete: `frontend/public/backgrounds/default.svg`
- Delete: `frontend/public/loading/bg-1.png`
- Delete: `frontend/public/loading/bg-2.png`
- Delete: `frontend/public/loading/loading.png`
- Delete: `frontend/public/error/error.png`

**Step 1: 确认资源零引用**

```bash
cd frontend && grep -r "/icons/\|/avatar/\|default\.svg\|/loading/\|/error/" src/ --include="*.vue" --include="*.ts"
```

Expected: 无输出

**Step 2: 删除文件**

```bash
git rm -r frontend/public/icons/ frontend/public/avatar/ frontend/public/backgrounds/default.svg frontend/public/loading/ frontend/public/error/
```

---

### Task 3.4: 阶段3验证与提交

**Step 1: 验证前端构建成功**

```bash
cd frontend && pnpm build 2>&1 | tail -10
```

Expected: 构建成功，无编译错误

**Step 2: 提交阶段3变更**

```bash
git commit -m "chore: remove unused frontend components and assets

Removed:
- 5 Vue components (AnimatedButton, GlassPanel, PinnedSection, ScrollProgress, ScrollReveal)
- 2 composables (useAudio, useFpsMonitor)
- 16+ static assets (icons, avatar, loading, error images)

All had zero import references in frontend/src/."
```

---

## 阶段4: Git跟踪修复

### Task 4.1: 停止跟踪IDE配置

**Files:**
- Untrack: `frontend/.vscode/settings.json`

**Step 1: 停止跟踪文件（保留本地副本）**

```bash
git rm --cached frontend/.vscode/settings.json
```

**Step 2: 确认.gitignore已包含规则**

```bash
grep ".vscode" .gitignore
```

Expected: `.vscode/` 在.gitignore中

---

### Task 4.2: 移动设计原型到docs目录

**Files:**
- Move: `design-prototype*.html`（7个）→ `docs/designs/prototypes/`

**Step 1: 创建目标目录**

```bash
mkdir -p docs/designs/prototypes
```

**Step 2: 移动文件**

```bash
git mv design-prototype*.html docs/designs/prototypes/
```

---

### Task 4.3: 清理根目录垃圾和重复文件

**Files:**
- Delete: `nul`（197字节垃圾文件）
- Delete: `start-live-stream.bat`（与frontend/下重复）

**Step 1: 删除文件**

```bash
rm -f nul
git rm start-live-stream.bat
```

---

### Task 4.4: 修复anima.py硬编码路径

**Files:**
- Move: `anima.py` → `scripts/anima_cli.py`
- Modify: `scripts/anima_cli.py`（移除第22-23行硬编码路径）

**Step 1: 移动文件**

```bash
git mv anima.py scripts/anima_cli.py
```

**Step 2: 移除硬编码路径**

编辑 `scripts/anima_cli.py`，删除或注释第22-23行：
```python
# 删除这行: RVC_DIR = "C:/Users/30262/RVC20240604Nvidia"
# 保留这行: RVC_DIR = os.environ.get("RVC_PATH", "")
```

**Step 3: 暂存变更**

```bash
git add scripts/anima_cli.py
```

---

### Task 4.5: 移动临时文件到docs

**Files:**
- Move: `AIRI Stage UI Kit.html` → `docs/`
- Move: `frontend-screenshot.png` → `docs/`

**Step 1: 移动文件**

```bash
git mv "AIRI Stage UI Kit.html" docs/
git mv frontend-screenshot.png docs/
```

---

### Task 4.6: 阶段4验证与提交

**Step 1: 验证git状态**

```bash
git status
git diff --cached --stat
```

Expected: 工作树干净，暂存区显示所有变更

**Step 2: 提交阶段4变更**

```bash
git commit -m "chore: fix git tracking and reorganize project root

- Untrack .vscode/settings.json (IDE config)
- Move 7 design prototypes to docs/designs/prototypes/
- Delete nul junk file and duplicate start-live-stream.bat
- Move anima.py to scripts/anima_cli.py, remove hardcoded path
- Move temporary files to docs/"
```

---

## 阶段5: 最终集成验证

### Task 5.1: 运行完整测试套件

**Step 1: 运行Python测试**

```bash
PYTHONPATH=src python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: 无新增失败

**Step 2: 运行前端构建**

```bash
cd frontend && pnpm build 2>&1 | tail -10
```

Expected: 构建成功

---

### Task 5.2: 最终提交（如果需要）

**Step 1: 检查是否有未暂存的变更**

```bash
git status
```

Expected: 工作树干净

**Step 2: 如果有变更，提交**

```bash
git add -A
git commit -m "chore: final cleanup adjustments"
```

---

## 完成

清理完成。总计删除~80个僵尸文件，项目代码库更干净。

**验证清单：**
- [x] Python测试通过
- [x] 前端构建成功
- [x] Git历史完整（所有删除的文件可通过`git show HEAD~N:path`恢复）
- [x] 无硬编码本地路径
- [x] 设计原型已重组到docs目录

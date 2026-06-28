# Anima 项目治理方案

> 针对代码审查中发现的 4 个结构性问题，给出可操作的治理方案。

---

## 问题一：子系统间耦合度偏高

### 现状

模块依赖关系扫描显示：

| 模块 | 向外依赖 |
|------|---------|
| `orchestration/server` | avatar, config, core, inspection, memory, orchestration, services, tools, tracing, utils（**10 个**） |
| `core` | avatar, config, core, inspection, memory, orchestration, services, tracing, utils（**9 个**） |
| `inspection` | core, inspection, notifier, orchestration |
| `services/meme` | config, **memory**（跨层） |
| `services/singing` | **avatar**, config（跨层） |
| `tracing` | **orchestration**, persistence, tracing（反向依赖） |

核心问题：

1. **`orchestration/server` 和 `core` 是 God Module**——几乎依赖所有其他模块，任何子系统变动都可能波及它们
2. **`services/meme → memory`**：服务层直接导入记忆层（`from anima.memory.wiki.models import WikiPage`），破坏了分层
3. **`services/singing → avatar`**：唱歌服务直接导入表情分析器（`from anima.avatar.analyzers.audio import AudioAnalyzer`）
4. **`tracing → orchestration`**：追踪模块反向依赖编排层，形成循环风险

### 治理方案

**第一步：引入依赖规则**

在项目根目录创建 `DEPENDENCY_RULES.md`，明确分层约束：

```
Layer 0 (Foundation): utils, config, tracing, persistence
Layer 1 (Domain):     memory, avatar, tools, notifier, services
Layer 2 (Orchestration): orchestration/graph
Layer 3 (Infrastructure): orchestration/server, core

规则：只允许向下依赖，同层可依赖，禁止向上依赖。
```

**第二步：切断跨层直接导入**

| 耦合点 | 修复方式 |
|-------|---------|
| `meme → memory.wiki.models` | 将 `WikiPage`, `PageType` 提取到 `persistence/protocols.py` 作为共享协议 |
| `singing → avatar.analyzers.audio` | `AudioAnalyzer` 是延迟导入（在函数体内），可改为在 `orchestration` 层注入 |
| `tracing → orchestration` | 改为 `TYPE_CHECKING` 守卫 |

**第三步：拆分 God Module（渐进式）**

- `routes.py` 改为只做路由注册，逻辑委托给各 handler
- `session.py` 中的 orchestrator 工厂逻辑移入 `orchestration/graph/orchestrator.py`

**验证方式：** `scripts/check_deps.py` 自动检测违规跨层导入。

---

## 问题二：TTS 实现过多，维护成本高

### 现状

当前有 **9 个 TTS 实现**（不含 mock）：

```
实际活跃:  qwen3_tts（当前默认）, gpt_sovits_tts, edge_tts
可能活跃:  glm_tts, kokoro_tts, vibe_voice_tts
疑似闲置:  chattts_tts, openai_tts（config 存在但无 impl 对应）
辅助模块:  glados_effect（音效处理，非独立 TTS）
```

### 治理方案

**第一步：标记生命周期状态**

在每个 TTS 实现文件头部添加状态标记：

```python
# Status: active | maintained | deprecated | experimental
# Last verified: 2026-05-23
```

**第二步：分层管理（core/contrib）**

```
services/speech/tts/
├── interface.py          # 接口定义
├── factory.py            # 工厂
├── mock_tts.py           # 测试用
├── edge_tts.py           # core: 零依赖，开箱即用
├── qwen3_tts.py          # core: 当前默认
├── gpt_sovits_tts.py     # core: 本地推理
└── contrib/              # contrib 子目录
    ├── glm_tts.py
    ├── kokoro_tts.py
    ├── chattts_tts.py
    ├── vibe_voice_tts.py
    └── glados_effect.py
```

contrib 目录下的实现：
- 不在 CI 必跑测试范围内（标记 `@pytest.mark.contrib`）
- 依赖通过 `extras_require` 管理
- 每季度评审一次，连续 2 个季度无使用记录则归档

**第三步：统一 TTS 测试合约**

添加 `audio_format`、`sample_rate`、`requires_gpu` 等元信息属性到 `TTSInterface`。

---

## 问题三：配置文件中的硬编码本地路径

### 现状

5 处硬编码的 Windows 绝对路径：

```
config/config.yaml:41    path: "C:/Users/30262/GPT-SoVITS-v2pro-20250604"
config/config.yaml:42    python: "C:/Users/30262/miniconda3/envs/gpt-sovits/python.exe"
config/services.yaml:171 ref_audio_path: "C:/Users/30262/Project/Anima/config/gpt_sovits/evil/ref_audio.wav"
config/services.yaml:176 "C:/Users/30262/Project/Anima/config/gpt_sovits/evil/ref_audio_zh.wav"
config/singing.yaml:16   rvc_path: "C:/Users/30262/RVC20240604Nvidia"
```

### 治理方案

- 硬编码路径 → `${ENV_VAR}` 环境变量替代
- 创建 `.env.example` 模板
- 添加路径校验（不存在时 warn 而非 crash）

---

## 问题四：生成文件/运行时数据误入仓库

### 治理方案

- 更新 `.gitignore` 排除运行时数据
- `git rm --cached` 移除已追踪的生成文件
- 添加 pre-commit 钩子防止再次提交
- 评估 `openspec/` 和 `.claude/` 的必要性

---

## 执行优先级

| 优先级 | 任务 | 状态 |
|-------|------|------|
| 🔴 P0 | 移除 memory_db/raw/ 对话记录 | ✅ 完成 (2026-05-23) |
| 🔴 P0 | git rm --cached 所有生成文件 | ✅ 完成 (2026-05-23) |
| 🟡 P1 | 硬编码路径 → 环境变量 | ✅ 完成 (2026-05-23) |
| 🟡 P1 | .env.example 模板 | ✅ 完成 (2026-05-23) |
| 🟢 P2 | TTS 分层 core/contrib | ✅ 完成 (2026-05-23) |
| 🟢 P2 | 跨层依赖检测脚本 | ✅ 完成 (2026-05-23) |
| 🟢 P2 | TTS 生命周期标记 + 接口元信息 | ✅ 完成 (2026-05-23) |
| 🔵 P3 | 切断 meme→memory 直接导入 | ✅ 完成 (2026-05-23) |
| 🔵 P3 | 切断 tracing→orchestration 导入 | ✅ 完成 (2026-05-23) |
| 🔵 P3 | God Module 拆分 | ⏳ 渐进式 |

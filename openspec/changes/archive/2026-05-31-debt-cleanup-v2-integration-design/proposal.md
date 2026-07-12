# Animetta 全面债务清除 + LivingMemory V2 集成设计

**日期**: 2026-05-31
**状态**: 已批准
**前置**: living-memory-architecture-design.md (Living Memory V2)

---

## 概述

将 LivingMemorySystem V2 接入 LangGraph 编排引擎，同时系统性清除所有历史债务——`$$$` 占位符、legacy 模块、过期导入路径、运行时 NameError。

**核心原则**：不考虑向后兼容。所有改动都是对未来的投资。

### 四阶段策略

```
Phase 1: V2 接入 LangGraph (6 touchpoints, net -38 行)
    │
Phase 2: 清理 Legacy Memory 模块 (git mv 30 文件 + 删除旧逻辑)
    │
Phase 3: 清理测试债务 (ast-grep 批量修复 120 文件, 931 $$$)
    │
Phase 4: 修复残留 NameError (源码层 ~70 文件)
```

---

## Phase 1: V2 接入 LangGraph

### 触点 1: state.py — 清理 + 新增

**删除**:
- `fuzzy_memories: List[str]` — V2 recall() 返回 summary 替代
- `injection_tier: int` — V2 不需要层级概念
- `user_query_depth: int` — 同上
- `meme_candidates: List[Dict[str, Any]]` — Meme 变成 EMERGENT 层 atom
- `meme_injected: bool` — 同上

**新增**:
- `emotion_vad: Optional[tuple[float, float, float]]` — VAD 情绪向量

### 触点 2: emotion_node.py — 离散 → VAD

在返回 `state["emotion"]` 之前，添加 VAD 映射:
```python
from animetta.memory.v2.emotion_field import VAD_MAP
vad = VAD_MAP.get(emotion_data.primary, VAD_MAP["neutral"])
return {"emotion": emotion_data.primary, "emotion_vad": vad.to_tuple()}
```

### 触点 3: output_node.py — 存储改造

**删除**: `from ...memory.models.turns import MemoryTurn`（整个代码库中 memory 模块唯一的硬导入）

**替换**: `_store_conversation_to_memory()` 改为调用 `memory_system.encode()`，传入 VAD 向量。

### 触点 4: memory_middleware.py — 检索统一

**删除**: FuzzyLayer + UserProfile + MemePool 三个独立调用

**替换**: 统一 `memory_system.recall(query, session_id, current_emotion)` — 返回 atoms、profile、memes

### 触点 5: llm_node.py — 适配接口

`_retrieve_memory_context()` 适配新的 middleware 接口签名。

### 触点 6: service_context.py — 初始化 + 修复 bug

**修复**: `MemorySystem` 从未被导入的 NameError bug（pre-existing）

**替换**: `init_memory()` 创建 `LivingMemorySystem` 代替旧 `MemorySystem`

---

## Phase 2: 清理 Legacy Memory 模块

### 操作

```
保留:
  memory/v2/        — V2 核心
  memory/storage/    — Chroma + SQLite 驱动（未来 AtomStore 需要）
  memory/wiki/       — 只读存档导出层

移入 _legacy/:
  system.py, manager.py, fuzzy_layer.py, fact_extractor.py,
  user_profile.py, prompts.py, tools.py, config.py,
  models/, search/, stores/, meme/, learner/, fuzzy/
```

### 同步删除

- `orchestrator.py`: `_query_depth_map` + `_compute_injection_tier()` 方法
- `memory_handlers.py` + `meme_handlers.py`: 旧的 WebSocket handler（功能已被 V2 recall() 替代）
- `config/features/memory.yaml`: 旧 init_memory() 的配置文件

---

## Phase 3: 清理测试债务

### 问题 A: 931 处 `$$$` 占位符（120 测试文件）

**策略**: 不改 `animetta/__init__.py` 桶文件。用脚本分析每个测试文件中实际使用的符号，将 `from animetta import $$$` 替换为正确的子模块导入路径。

**分类映射**:

| 测试文件类型 | $$ 替换为 |
|-------------|---------|
| test_llm_providers.py | `from animetta.services.intelligence.llm import MockLLM, ...` |
| test_tts_providers.py | `from animetta.services.speech.tts import MockTTS, ...` |
| test_*_node.py (graph) | `from animetta.orchestration.graph import llm_node, ...` |
| test_memory_*.py | `from animetta.memory._legacy import MemorySystem, ...` |
| test_base.py (tools) | `from animetta.tools import calculator, ...` |

### 问题 B: 30+ 文件使用过期 `src.anima` 路径

批量替换 `src.anima` → `animetta`。

---

## Phase 4: 修复残留 NameError

### 层 A: V2 集成路径（必须修复）

| 文件 | 修复 |
|------|------|
| `service_context.py` | Phase 1 已覆盖（MemorySystem → LivingMemorySystem）|
| `llm_node.py` | 检查 `_retrieve_memory_context` 使用的实际符号 |
| `emotion_node.py` | Phase 1 已覆盖（VAD_MAP 导入）|

### 层 B: 非关键路径（脚本批量修复）

~70 个源文件（factory.py, *_llm.py, *_tts.py 等）——和 Phase 3 同一套脚本工具。

**不阻塞 V2 上线**——这些文件只在对应功能被调用时触发 NameError，V2 的记忆路径不经过它们。

---

## 改动总览

| Phase | 操作 | 规模 |
|-------|------|------|
| 1 | 修改 6 个 LangGraph 文件 | ~80 删, ~42 增 |
| 2 | 移动 30+ 旧模块, 删除 3 个配置/逻辑文件 | ~30 git mv, ~40 行删除 |
| 3 | 修复 120 测试文件 | 931 $$$ → 正确导入 |
| 4 | 修复 ~70 源文件 | 和 Phase 3 同脚本 |

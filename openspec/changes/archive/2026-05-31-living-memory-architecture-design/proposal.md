# Animetta 活性记忆架构设计 (Living Memory V2)

**日期**: 2026-05-31
**状态**: 已批准
**作者**: Sisyphus + User
**前置**: ADR-002 (Hybrid Search), ADR-005 (Wiki Memory)

---

## 概述

将 Animetta 的记忆系统从"数据库"升级为"活系统"。三个认知科学驱动的核心创新：

1. **回忆即重写 (Reconsolidation)** — 每次检索触发 LLM 对记忆的重述写回，记忆随每次回忆而改变
2. **情绪场 (Emotional Field)** — VAD 三维向量渗透编码/检索/重述/代谢，替代离散标签
3. **记忆代谢 (Metabolism)** — 统一衰减/巩固/遗忘循环，遗忘是 feature 不是 bug

### 设计决策

| 决策 | 选项 |
|------|------|
| 重构范围 | 推倒重来 — 只复用 Chroma + SQLite 存储驱动 |
| 数据模型 | 统一 MemoryAtom，所有记忆类型是同一实体在不同层的投射 |
| 再巩固触发 | 检索触发 — 每次检索异步 LLM 重述写回 |
| 情绪建模 | VAD 三维向量 (Valence, Arousal, Dominance) |

---

## Section 1: MemoryAtom — 统一记忆体

一段对话、一条知识、一个梗、一段 wiki 页面——都是同一个 `MemoryAtom` 在不同层 (layer) 上的投射。

```
RAW ──Compile──▶ EPISODIC ──Digest──▶ SEMANTIC ──Emerge──▶ EMERGENT
(对话原文)       (经历摘要)         (提炼知识)         (梗/综合)
```

### 字段定义

```python
@dataclass
class MemoryAtom:
    # ── 标识 ──
    id: str                           # UUID7 (时间有序)
    layer: Layer                      # RAW | EPISODIC | SEMANTIC | EMERGENT

    # ── 内容 ──
    content: str                      # 记忆文本（人类可读，Wiki 持久化内容）
    summary: str | None               # 摘要（随每次再巩固更新，越来越"模糊"）

    # ── 双时态（灵魂字段）──
    occurred_at: datetime             # 事实发生时间
    rewritten_at: datetime            # 最后一次再巩固写入时间
    version: int                      # 每次再巩固 +1
    version_chain: list[str]          # [v1_id, v2_id, v3_id...] 可追溯演化史

    # ── 活性指标 ──
    confidence: float                 # 0.0-1.0
    salience: float                   # f(confidence, retrieval, recency, emotion)
    retrieval_count: int              # 被检索次数
    last_accessed_at: datetime | None

    # ── 情绪向量 (VAD) ──
    emotion_valence: float            # -1.0 ~ +1.0
    emotion_arousal: float            # 0.0 ~ 1.0
    emotion_dominance: float          # -1.0 ~ +1.0

    # ── 图谱 ──
    source_ids: list[str]             # 父原子
    relations: list[Relation]         # UPDATES | EXTENDS | DERIVES | EVOKES | CONTRADICTS
    tags: list[str]

    # ── 代谢参数 ──
    decay_rate: float                 # 个性化衰减率
    forget_at: datetime | None        # 预计遗忘时间
    is_archived: bool                 # 已归档（不参与检索，可被恢复）
```

### Layer 语义

| Layer | 来源 | 生命周期 | 例子 |
|-------|------|---------|------|
| `RAW` | 对话原文 | 短期 (1-3天) | "用户: 我今天喝了杯拿铁..." |
| `EPISODIC` | Compile 提炼 | 中期 (1-4周) | "用户喜欢喝咖啡，今天买了拿铁" |
| `SEMANTIC` | Digest 提炼 | 长期 (数月) | "用户偏好: 咖啡(拿铁>美式)" |
| `EMERGENT` | 多次 SEMANTIC 涌入 | 检索热度维持 | 梗: "拿铁战士" / 综合趋势 |

---

## Section 2: ReconsolidationEngine — 回忆即重写

每次检索触发异步 LLM 重述，用当前上下文/情绪/话题染色后写回。

### 触发流程

```
retrieve_context(query, session_id)
    └──→ 返回匹配 MemoryAtoms
    └──→ 异步触发 reconsolidate(atoms, context)
              │
              ReconsolidationContext:
                - current_query
                - current_emotion: VADVector
                - dialogue_topic
                - session_id
              │
              ▼
         [LLM 重述]
              │
              ├── 新 summary（染色版本）
              ├── 新 confidence（±0.1）
              ├── 新 emotion_vector（偏向当前情绪）
              ├── 新 decay_rate（被回忆 → 衰减变慢）
              └── version++ → AtomStore
```

### LLM Prompt 模板

```
你是 Animetta 的记忆系统。你正在"回忆"一段记忆。

【原始记忆】（版本 {version}，上次改写于 {rewritten_at}）
{content}

【当前语境】
- 对话主题: {dialogue_topic}
- 当前情绪: (V:{valence}, A:{arousal}, D:{dominance})
- 检索原因: {current_query}

【任务】
用当前语境的视角重新表达这段记忆。规则：
1. 核心事实不可改变
2. 语气和措辞可被当前情绪染色
3. 如果当前语境和记忆有关联，自然地强化关联
4. 长度不超过原文的 120%
5. 若 version > 5，可融入旧版本口吻

输出 JSON:
{"summary": "...", "confidence_delta": 0.05, "emotion_shift": [0.1, 0.0, -0.05]}
```

### 节流机制

| 机制 | 规则 |
|------|------|
| 冷却期 | 同一原子 ≥ 30min |
| 显著性门槛 | 只重写 salience > 0.3 |
| 批上限 | 单次最多 3 个原子 |
| 内容阈值 | 编辑距离 < 5% 则跳过写回 |

### 成本估算

每轮对话 +1 次 flash 模型 LLM 调用。

---

## Section 3: EmotionalField — 情绪是场

VAD 三维连续向量替代离散标签，渗透编码/检索/重述/代谢。

### VAD 模型

```
Valence  -1.0(负面) ←── 0 ──→ +1.0(正面)
Arousal   0.0(平静) ←── 0.5 ──→ 1.0(激动)
Dominance -1.0(被动) ←── 0 ──→ +1.0(主导)
```

### 离散 → VAD 映射

| 标签 | V | A | D | 标签 | V | A | D |
|------|---|---|---|------|---|---|---|
| happy | +0.8 | +0.6 | +0.7 | suspicious | -0.4 | +0.4 | -0.2 |
| excited | +0.9 | +0.9 | +0.8 | shy | +0.1 | +0.4 | -0.7 |
| love | +0.9 | +0.5 | +0.4 | tired | -0.1 | -0.6 | -0.4 |
| proud | +0.7 | +0.5 | +0.8 | resigned | -0.3 | -0.5 | -0.6 |
| neutral | 0.0 | 0.0 | 0.0 | sad | -0.8 | -0.3 | -0.6 |
| thinking | +0.1 | -0.3 | +0.3 | angry | -0.8 | +0.8 | +0.5 |
| confused | -0.2 | +0.3 | -0.5 | surprised | +0.3 | +0.8 | -0.3 |

### 渗透的四个环节

| 环节 | 情绪作用 |
|------|---------|
| **Encoding** | arousal → initial_confidence；valence 标记正负经历 |
| **Retrieval** | 当前 VAD × 原子 VAD 余弦相似度 → 20% 权重偏置 (mood-congruent recall) |
| **Reconsolidation** | 当前 VAD 传入 LLM 重述 prompt；原子 emotion_vector 向当前偏移 |
| **Metabolism** | 高 arousal → 衰减更慢 (flashbulb memory)；极端 valence → 更难遗忘 |

### 检索公式

```
score = 0.55 × vector_similarity + 0.25 × keyword_score + 0.20 × emotion_congruence
emotion_congruence = cosine_similarity(current_vad, atom.emotion_vector)
                    × (1.0 + 0.5 × current_arousal)
```

---

## Section 4: MetabolismScheduler — 记忆代谢

统一三阶段循环：衰减 → 巩固 → 遗忘。

### 统一代谢公式

```
salience(t) = confidence × e^(-decay_rate × t)
            × (1.0 + 0.15 × retrieval_count)
            × (1.0 + 0.3 × |valence| × arousal)
```

### 三阶段循环 (每 6h)

```
Phase 1: DECAY
  salience < 0.5 → 降级 ranking 权重
  salience < 0.2 → 标记 "dim"

Phase 2: CONSOLIDATE (仅每日 tick)
  LLM 扫描语义重叠原子对 → 合并为新 SEMANTIC 原子
  新原子 confidence = weighted_avg

Phase 3: FORGET
  salience < threshold → archive
  threshold 自适应: 原子数/容量上限
    低水位(<50%) → 0.05 (几乎不遗忘)
    高水位(>80%) → 0.20 (积极遗忘)
```

---

## Section 5: AtomStore — 持久化层

复用 Chroma + SQLite 驱动，统一 CRUD。

### 三层存储

**SQLite (结构层)**:
- `memory_atoms` 表 — 所有原子字段
- `memory_relations` 表 — 原子间关系
- `memory_fts` (FTS5) — content + summary 全文索引
- `memory_versions` 表 — 版本演化史

**Chroma (向量层)**:
- 每个 atom 一个向量 (embedding of content + summary)
- metadata: {layer, confidence, salience, emotion_v, emotion_a, emotion_d}

**文件系统 (Wiki 导出层)**:
- 定期从 SQLite 导出 Markdown (保留 ADR-005 精神)
- 路径: `memory_db/wiki/{layer}/{id[:8]}.md`

### 检索接口

```python
class AtomStore:
    async def search(
        self, query: str,
        current_emotion: VADVector | None = None,
        layer: Layer | None = None,
        min_salience: float = 0.1,
        limit: int = 20,
    ) -> list[SearchResult]: ...

    async def create_version(
        self, atom_id: str,
        new_summary: str,
        new_confidence: float,
        new_emotion: VADVector,
    ) -> MemoryAtom: ...
```

---

## Section 6: LangGraph 集成

### 三个触点

| 触点 | 文件 | 改动 | 说明 |
|------|------|------|------|
| 检索 | `memory_middleware.py` | 重写 | `fuzzy_layer + profile + meme` → `memory_system.recall()` |
| 编码 | `output_node.py` | 中度 | `store_turn()` → `encode()`；传入 `emotion_vad` |
| VAD 转换 | `emotion_node.py` | 微调 | 加一行 `VAD_MAP[primary]` |
| State | `state.py` | 微调 | 新增 `emotion_vad` 字段 |
| LLM | `llm_node.py` | 微调 | 适配新检索接口 |
| 初始化 | `service_context.py` | 中度 | `init_memory()` → `LivingMemorySystem` |

### 新接口

```python
class LivingMemorySystem:
    async def recall(query, session_id, current_emotion) -> RecallResult:
        """检索 + 注入 LLM prompt + 异步触发再巩固"""
    
    async def encode(user_input, agent_response, emotion_vad, session_id) -> MemoryAtom:
        """对话编码为 RAW atom + 异步触发 Compile pipeline"""
```

---

## 文件结构

```
src/animetta/memory/
├── _legacy/                  # 旧模块（渐进废弃）
│   ├── fuzzy_layer.py
│   ├── manager.py
│   ├── meme/
│   ├── learner/
│   └── ...
├── storage/                  # 复用（不改）
│   ├── sqlite.py
│   └── chroma.py
├── v2/                       # 新核心
│   ├── __init__.py
│   ├── system.py             # LivingMemorySystem
│   ├── atom.py               # MemoryAtom + Layer + Relation
│   ├── store.py              # AtomStore
│   ├── reconsolidation.py    # ReconsolidationEngine
│   ├── emotion_field.py      # EmotionalField + VAD_MAP
│   ├── metabolism.py         # MetabolismScheduler
│   ├── search.py             # 混合检索
│   ├── compile.py            # CompileEngine
│   └── config.py             # MemoryV2Config
├── models/                   # 精简（仅旧模块用）
├── wiki/                     # 降级为导出层
└── tools.py                  # 适配新接口
```

---

## 与现有系统的替换关系

| 现有模块 | V2 替代 |
|---------|---------|
| `MemorySystem` | `LivingMemorySystem` |
| `MemoryTurn` + `MemoryEntry` + `WikiPage` + `FuzzyMemory` | `MemoryAtom` (四层统一) |
| `MemoryEntryStore` | `AtomStore` |
| `MemoryScorer.compute_decay()` + `MemePool._effective_score()` | `MetabolismScheduler` (统一 salience 公式) |
| `FuzzyLayer` | 不再需要 — 检索返回的 `summary` 即模糊化版本 |
| `WikiManager` (主存储) | 降级为导出层 |
| `PeriodicLearner` 中的 decay/prune 任务 | `MetabolismScheduler.tick()` |
| `emotion_node` 离散标签 | VAD 向量转换 |

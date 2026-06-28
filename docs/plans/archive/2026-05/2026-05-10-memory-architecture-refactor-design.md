# 记忆模块架构重构设计

## 现状问题

当前记忆系统有三个平行持久存储 + 一套独立学习日志，LLM 需要从多个来源捞数据：

```
MemorySystem
├── WikiManager        (长期知识库: entities/concepts/synthesis)
├── FuzzyMemoryStore   (模糊叙述记忆, 独立 SQLite)
├── MemePool           (梗池, 独立 SQLite)
└── PeriodicLearner     (学习日志, 又一套 SQLite)
```

问题：
1. 三个平行存储，数据有冗余、一致性难保证
2. FuzzyMemory 本质是 wiki 的"视图"，却独立存储
3. MemePool 数据本应是 wiki 页面的一种类型
4. 前端需要搜索按钮来手动查记忆，说明自动注入不够

## 目标架构

```
MemorySystem
├── ShortTermMemory            (内存, 最近 20 轮)
├── WikiManager                (唯一持久层)
│   ├── entities/              (实体: 用户画像等)
│   ├── concepts/              (概念: 跨时间线主题)
│   ├── synthesis/             (合成页: LLM 整理结果)
│   └── memes/                 (梗: page_type="meme")
├── FuzzyLayer                 (虚层, 纯计算, 不落盘)
│   └── ShortTerm + Wiki → 实时合成模糊叙述 → 注入 LLM
└── MemoryMiddleware           (自动三级注入, 去搜索)
```

## 关键决策

### 1. Wiki 统一存储
- MemeStore (独立 SQLite) 删除，Meme CRUD 改为 WikiManager.write_page()
- Meme 字段 (is_active, current_score, use_count) 存入 WikiPage.metadata JSON
- 现有 FuzzyMemory 一次性迁移为 wiki/synthesis/ 页面
- 学习日志改写入 wiki，不再独立 SQLite

### 2. Fuzzy 变虚层
- FuzzyMemoryStore + FuzzyConsolidator 合并为 fuzzy_layer.py
- 不再独立存储，每次 LLM 调用前实时合成
- 加进程内 LRU 缓存 (max 100, TTL 5min) 避免重复计算

### 3. 去掉搜索按钮
- 删除 get_fuzzy_memeries / get_fuzzy_memory_sources 事件
- MemoryMiddleware 自动做三级注入
- 记忆面板改为显示 wiki 最近更新页面列表

### 4. 调度任务调整
- consolidate → 写 wiki sources/
- extract_patterns → 写 wiki concepts/
- generate_meme_candidates → 写 wiki memes/
- maintain_meme_pool → 扫 wiki memes/ 更新评分 metadata
- prune_logs → 清理 wiki 过期页面

## 迁移路径

1. 先在 WikiPage 模型加 metadata JSON 字段
2. 实现 Meme → Wiki 的适配层 (MemePool 读写走 wiki)
3. 将 FuzzyMemory 批量迁移为 wiki synthesis 页面
4. 实现 FuzzyLayer 虚层 (从 wiki + short-term 实时合成)
5. 改 MemoryMiddleware 注入源为 FuzzyLayer
6. 去掉前端搜索，改成 wiki 页面浏览
7. 删除废弃的 SQLite 表

# Memory System Architecture

三层记忆系统的架构文档。

## 组件

### 1. ShortTermMemory
- **位置**: `src/anima/memory/short_term.py`
- **用途**: 会话级快速存储（内存）
- **容量**: 默认 20 轮对话
- **特点**: 自动清理旧数据

### 2. LongTermMemory
- **位置**: `src/anima/memory/long_term.py`
- **用途**: 持久化存储（SQLite）
- **特点**: 跨会话保存，支持全文搜索

### 3. MemorySystem
- **位置**: `src/anima/memory/memory_system.py`
- **用途**: 统一协调三层存储
- **API**:
  - `store_turn()` - 存储对话
  - `retrieve_context()` - 检索相关记忆
  - `get_user_history()` - 获取历史

## 数据流

```
ConversationOrchestrator
    ↓
MemorySystem
    ↓
    ├─→ ShortTermMemory (内存)
    ├─→ LongTermMemory (SQLite)
    └─→ ImportanceScorer (评分)
```

## 配置

```yaml
# config/features/memory.yaml
memory:
  enabled: true
  short_term:
    max_turns: 20
  long_term:
    backend: sqlite
    db_path: data/memories.db
  importance:
    threshold: 0.7
```

## 初始化

运行脚本初始化数据库：

```bash
python scripts/init_memory_db.py
```

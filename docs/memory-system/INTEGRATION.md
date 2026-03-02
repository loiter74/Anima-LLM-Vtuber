# Memory System Integration

记忆系统已成功集成到 Anima 项目中。

## 已完成的集成

### 1. ServiceContext 集成

**文件**: `src/anima/service_context.py`

- 添加 `memory_system` 字段
- 新增 `init_memory()` 方法，从 `config/features/memory.yaml` 加载配置
- 在 `load_from_config()` 中自动初始化记忆系统
- 在 `close()` 中清理记忆系统资源

### 2. ConversationOrchestrator 集成

**文件**: `src/anima/services/conversation/orchestrator.py`

- 在 `__init__` 中接收 `memory_system` 参数
- 在 `_process_conversation()` 中：
  - **对话前**: 检索相关记忆并注入到输入文本
  - **对话后**: 将对话存储到记忆系统（自动评估重要性）
- 新增 `_format_memory_context()` 方法格式化记忆上下文

### 3. Socket.IO 服务器集成

**文件**: `src/anima/socketio_server.py`

- 在创建 ConversationOrchestrator 时传递 `memory_system`

## 工作流程

```
用户输入 → ConversationOrchestrator
    ↓
检索相关记忆 (retrieve_context)
    ↓
格式化记忆上下文
    ↓
注入到输入文本
    ↓
LLM 处理
    ↓
生成响应
    ↓
存储对话到记忆系统 (store_turn)
    ↓
评估重要性 (ImportanceScorer)
    ↓
高重要性(≥0.7) → 存储到长期记忆 (SQLite)
低重要性(<0.7) → 仅存储到短期记忆 (Deque)
```

## 记忆注入格式

```
[相关的历史对话]
1. 用户: 你好，我叫小明
   AI: 你好小明！很高兴认识你。
2. 用户: 记住，我喜欢编程
   AI: 好的，我记住了你喜欢编程。

[当前对话]
小明喜欢什么？
```

## 测试

运行测试脚本验证功能：

```bash
python tests/test_memory_integration.py
```

测试输出：
```
============================================================
Testing Memory System
============================================================
OK - Memory system initialized

Storing conversations...
OK - Stored: Hello, my name is Xiao Ming... (importance: 0.65)
OK - Stored: Remember, I like programming... (importance: 0.65)
OK - Stored: How is the weather today?... (importance: 0.65)

Retrieving related memories...
Query: What does Xiao Ming like?
Found 3 related memories:
1. User: Hello, my name is Xiao Ming
   AI: Hello Xiao Ming! Nice to meet you.
2. User: Remember, I like programming
   AI: Got it, I remember you like programming.
...
```

## 配置

**文件**: `config/features/memory.yaml`

```yaml
memory:
  enabled: true
  short_term:
    max_turns: 20  # 短期记忆容量
  long_term:
    backend: sqlite
    db_path: data/memories.db
  importance:
    threshold: 0.7  # 长期存储阈值
    base_score: 0.5  # 基础分数
```

## 重要性评分因素

`ImportanceScorer` 评估对话重要性（0-1）：

1. **长度加分**：长对话更重要
   - 总长度 > 200字符: +0.1
   - 总长度 > 500字符: +0.1

2. **情感强度**：极端情绪更重要
   - 包含 happy/sad: +0.15

3. **提问检测**：用户在询问
   - 包含疑问词: +0.15

4. **关键词检测**：用户明确表示重要性
   - 包含"记住"、"重要"、"喜欢"等: +0.15

## API 用法

```python
from anima.memory import MemorySystem, MemoryTurn
from datetime import datetime
import uuid

# 初始化
config = {
    "short_term_max_turns": 20,
    "long_term_db_path": "data/memories.db",
    "importance_threshold": 0.7
}
memory = MemorySystem(config)

# 存储对话
turn = MemoryTurn(
    turn_id=str(uuid.uuid4()),
    session_id="session_001",
    timestamp=datetime.now(),
    user_input="你好",
    agent_response="你好！",
    emotions=["happy"],
    metadata={}
)
await memory.store_turn(turn)

# 检索相关记忆
memories = await memory.retrieve_context(
    query="用户说了什么？",
    session_id="session_001",
    max_turns=3
)

# 获取历史记录
history = await memory.get_user_history(
    session_id="session_001",
    limit=50
)

# 清理会话
await memory.clear_session("session_001")

# 关闭记忆系统
memory.close()
```

## 数据持久化

**数据库**: `data/memories.db` (SQLite)

表结构：
- `memories` - 主表
- `memories_fts` - 全文搜索表 (FTS5)

索引：
- `(session_id, timestamp DESC)` - 按会话和时间查询

## 已知限制

1. **向量搜索未实现**: 当前使用 FTS5 全文搜索，不支持语义搜索
2. **知识图谱未实现**: Entity 和 Relation 数据结构已定义，但未实现存储
3. **重要性评分规则简单**: 基于规则，可以考虑升级到 ML 模型

## 下一步优化建议

1. **向量嵌入**:
   - 集成 sentence-transformers
   - 实现语义相似度搜索
   - 将向量存储到 SQLite 或专用向量数据库

2. **知识图谱**:
   - 实现实体和关系提取
   - 存储到图数据库 (Neo4j) 或图结构 (NetworkX)

3. **重要性评分**:
   - 使用训练模型替代规则
   - 考虑对话轮次、时间衰减等因素

4. **记忆总结**:
   - 自动总结长对话
   - 生成记忆摘要
   - 支持跨会话的主题追踪

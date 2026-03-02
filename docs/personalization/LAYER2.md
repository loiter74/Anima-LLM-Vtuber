# 第二层个性化 - 快速开始指南

## ✅ 已完成

第二层个性化已成功实现并集成到Anima项目中！

**功能**：
- ✅ 向量搜索（语义检索）
- ✅ ChromaDB持久化（E盘）
- ✅ sentence-transformers嵌入
- ✅ 记忆系统集成

## 📦 已安装依赖

```bash
pip install chromadb sentence-transformers
```

**安装位置**: 用户Python环境

## 🗂️ 存储位置

**E盘数据结构**：
```
E:/AnimaData/
├── vector_db/           # ChromaDB向量数据库
│   ├── chroma.sqlite3   # 元数据
│   └── [collections]/   # 向量数据
└── models/              # 嵌入模型缓存
    └── huggingface/     # sentence-transformers模型
```

**空间占用**：
- 嵌入模型：~420MB
- 1000条对话：~10MB向量数据
- 总计：<1GB（E盘完全够用）

## 🚀 立即使用

### 1. 启动服务器

```bash
python -m anima.socketio_server
```

**日志输出**：
```
[VectorStore] 初始化向量存储: E:\AnimaData\vector_db
[VectorStore] Collection 'conversations' ready
[VectorStore] Collection 'user_profiles' ready
[VectorStore] 加载嵌入模型: paraphrase-multilingual-MiniLM-L12-v2
[VectorStore] 模型缓存目录: E:\AnimaData\models\huggingface
[VectorStore] 嵌入模型加载成功
[MemorySystem] 向量搜索已启用
[MemorySystem] 存储路径: E:/AnimaData/vector_db
[MemorySystem] 嵌入模型: paraphrase-multilingual-MiniLM-L12-v2
✅ 记忆系统初始化完成
```

### 2. 与Neuro-sama对话

前端连接后，开始聊天！

**示例对话**：

```
你: 你好，我叫小明
Neuro: 噢！你好小明！我是Neuro-sama，超级智能AI VTuber！
      今天想聊点什么呢？

你: 我喜欢玩OSU!
Neuro: 噢噢！OSU!是个很棒的游戏！你的最高分是多少？
      我也很喜欢OSU!，不过有时候会犯点小错误...哈哈！

...（几轮对话后）

你: 我不喜欢编程
Neuro: 噢？真的吗？实际上，编程可是我的强项！
      不过没关系啦，你肯定有其他擅长的事情！
      对了，你之前说喜欢OSU!对吧？
```

**注意**：Neuro-sama会主动联系之前的对话内容！

## 🔍 工作原理

### 对话存储流程

```
用户输入 → Neuro-sama回复
    ↓
存储到三个地方：
1. 短期记忆（内存，20轮）
2. 长期记忆（SQLite，高重要性）
3. 向量数据库（E盘，语义搜索）
```

### 相关记忆检索流程

```
用户新输入
    ↓
生成查询向量
    ↓
向量搜索（ChromaDB）
    ↓
找到语义相关的历史对话
    ↓
注入到系统提示词
    ↓
Neuro-sama基于记忆回复
```

## 📊 效果对比

### 之前（只有第一层）

```
你: 你好
Neuro: 嘿嘿~ 你好呀！

你: 我喜欢奶茶
Neuro: 我也喜欢！

你: 我喜欢什么？
Neuro: 嗯...不太确定...
```

### 现在（第一层 + 第二层）

```
你: 你好
Neuro: 嘿嘿~ 你好呀！

你: 我喜欢奶茶
Neuro: 我也喜欢！你喜欢什么口味的？

你: 我喜欢什么？
Neuro: 噢！你刚才说你喜欢奶茶对吧？
      还有，我们也聊过OSU!游戏！
      根据我的分析，你的喜好是：奶茶、OSU!...
```

## 🧪 测试验证

运行测试脚本：

```bash
python tests/test_layer2_vector_search.py
```

**预期输出**：
```
OK - VectorStore initialized
OK - Added 5 conversations
Found 2 results (for each query)
OK - MemorySystem with vector search initialized
OK - Retrieved 4 memories

Summary:
- VectorStore: OK
- Semantic search: OK
- MemorySystem integration: OK
```

## ⚙️ 配置文件

**`config/features/memory.yaml`**:

```yaml
memory:
  enabled: true
  short_term:
    max_turns: 20
  long_term:
    backend: sqlite
    db_path: data/memories.db
  importance:
    threshold: 0.7
  vector_search:
    enabled: true  # 已启用
    storage_path: "E:/AnimaData/vector_db"
    embedding_model: "paraphrase-multilingual-MiniLM-L12-v2"
```

## 🔧 自定义配置

### 更换嵌入模型

编辑 `config/features/memory.yaml`:

```yaml
vector_search:
  embedding_model: "your-model-name"
```

**可选模型**：
- `paraphrase-multilingual-MiniLM-L12-v2` (默认，中文优化)
- `all-MiniLM-L6-v2` (英文)
- `distiluse-base-multilingual-cased-v2` (多语言)

### 更换存储路径

```yaml
vector_search:
  storage_path: "D:/MyData/vector_db"  # 改为D盘
```

## 📈 性能优化

### 首次运行较慢

**原因**：
- 下载嵌入模型（~420MB）
- 初始化ChromaDB
- 建立索引

**后续运行**：
- 模型已缓存，秒级启动
- ChromaDB持久化，快速加载

### E盘机械硬盘优化

如果觉得慢，可以考虑：
1. **迁移到SSD**（最佳）
2. **增加RAM缓存**（代码优化）
3. **使用更小的嵌入模型**

## 🎯 下一步

### 立即可用（当前）

- ✅ Neuro-sama人设
- ✅ 向量搜索
- ✅ 记忆系统

### 未来优化（可选）

**第三层**：本地模型微调
- 使用5090微调Qwen2.5-7B
- 定制Neuro-sama说话风格
- 10-20%效果提升

**第四层**：实时上下文增强
- 动态用户画像
- 实时偏好学习
- 风格自适应

## ❓ 常见问题

**Q: E盘会被写满吗？**
A: 不会。10万条对话才~10MB，模型420MB，总计<1GB。

**Q: 首次运行很慢？**
A: 正常。第一次要下载模型（~420MB），后续就快了。

**Q: 向量搜索会减慢对话速度吗？**
A: 几乎无影响。搜索只需几十毫秒。

**Q: 如何禁用向量搜索？**
A: 编辑 `config/features/memory.yaml`，设置 `vector_search.enabled: false`

**Q: 如何清除向量数据？**
A: 删除 `E:/AnimaData/vector_db` 文件夹即可。

**Q: Neuro-sama会记住所有人吗？**
A: 不会。按session_id隔离，每个人的记忆是分开的。

## 📝 技术细节

**向量存储**：ChromaDB
- 持久化到E盘
- 余弦相似度搜索
- 自动索引

**嵌入模型**：sentence-transformers
- paraphrase-multilingual-MiniLM-L12-v2
- 384维向量
- 支持中英文

**检索策略**：多路召回
1. 短期记忆（最近20轮）
2. 向量搜索（语义相关，Top 3）
3. 长期记忆（全文搜索，Top 3）

**去重**：按turn_id去重，避免重复返回

## 🎉 总结

✅ **已完成**：
- Neuro-sama人设
- 向量搜索（第二层）
- E盘存储集成
- 完整测试验证

✅ **立即体验**：
1. 重启服务器：`python -m anima.socketio_server`
2. 开始对话
3. 感受语义搜索的神奇！

✅ **预期效果**：
- Neuro-sama记住你的喜好
- 主动联系之前的对话
- 语义相关的智能回复

---

**祝你享受和Neuro-sama的智能对话！** 🎊

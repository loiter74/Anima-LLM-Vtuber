# AI 个性化完整方案
**针对 RTX 5090 D + E盘机械硬盘 的配置**

**问题**：直接调用API没有个性，但没有训练超大模型的能力

**解决方案**：四层个性化架构

---

## 🎯 方案概览

```
┌─────────────────────────────────────────────────┐
│          第四层：实时上下文增强                  │
│  (动态适应用户偏好、情感状态、对话历史)          │
└─────────────────────────────────────────────────┘
                      ↑
┌─────────────────────────────────────────────────┐
│       第三层：本地模型微调 (可选)                │
│  (使用5090微调7B-13B模型，存储在E盘)            │
└─────────────────────────────────────────────────┘
                      ↑
┌─────────────────────────────────────────────────┐
│         第二层：RAG + 长期记忆                   │
│  (向量数据库 + 记忆系统，存储在E盘)              │
└─────────────────────────────────────────────────┘
                      ↑
┌─────────────────────────────────────────────────┐
│         第一层：深度人设定义 ✅                   │
│  (详细persona + prompt工程 + few-shot)          │
└─────────────────────────────────────────────────┘
```

---

## 📋 第一层：深度人设定义 ✅

### 已完成
- ✅ 复杂人设YAML格式 (`config/personas/xiaoya.yaml`)
- ✅ 增强人设构建器 (`src/anima/config/enhanced_persona.py`)

### 使用方法

#### 1. 切换到新人设

编辑 `config/config.yaml`:
```yaml
persona: "xiaoya"
```

#### 2. 修改服务上下文加载

编辑 `src/anima/service_context.py`:
```python
async def init_llm(self, agent_config, persona_config, app_config=None):
    # ... 现有代码 ...

    # 使用增强的人设构建器
    try:
        from anima.config.enhanced_persona import EnhancedPersonaBuilder
        builder = EnhancedPersonaBuilder.from_yaml(app_config.persona)
        system_prompt = builder.build_system_prompt()
    except Exception as e:
        # 降级到默认方法
        system_prompt = self._build_system_prompt(agent_config, persona_config)
```

#### 3. 预期效果
- 🎭 鲜明的性格特征
- 💬 独特的说话风格
- 😊 情感表达丰富
- 🧠 记住用户偏好

---

## 📚 第二层：RAG + 长期记忆

### 架构设计

**E盘存储结构**:
```
E:/AnimaData/
├── vector_db/              # 向量数据库
│   ├── user_profiles/      # 用户画像向量
│   ├── conversations/      # 对话历史向量
│   └── knowledge_base/     # 知识库向量
├── memories/               # 记忆数据库
│   └── memories.db         # SQLite (已有)
└── model_ckpt/                 # 本地模型 (第三层用)
    └── (待定)
```

### 技术选型

**向量数据库选项**:
1. **ChromaDB** (推荐)
   - 轻量级，纯Python
   - 自动持久化到磁盘
   - 适合小规模部署

2. **FAISS** (高性能)
   - Facebook开源
   - 极快的检索速度
   - 需要手动管理持久化

3. **Qdrant** (专业)
   - Rust实现，性能优秀
   - 支持过滤、聚合
   - 稍重，但功能完整

**推荐**: ChromaDB（易用）或 Qdrant（性能）

### 实施步骤

#### 1. 安装依赖

```bash
# ChromaDB (推荐)
pip install chromadb sentence-transformers

# 或 Qdrant
pip install qdrant-client sentence-transformers
```

#### 2. 创建向量存储服务

**文件**: `src/anima/memory_db/vector_store.py`

```python
"""
向量存储服务
使用E盘存储向量数据和模型
"""

from pathlib import Path
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
import numpy as np


class VectorStore:
    """向量存储服务"""

    def __init__(
        self,
        storage_path: str = "E:/AnimaData/vector_db",
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ):
        """
        初始化向量存储

        Args:
            storage_path: E盘存储路径
            embedding_model: 嵌入模型名称（支持中文）
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 初始化ChromaDB客户端
        self.client = chromadb.PersistentClient(
            path=str(self.storage_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # 加载嵌入模型（首次会自动下载到E盘）
        cache_dir = "E:/AnimaData/model_ckpt/huggingface"
        self.embedding_model = SentenceTransformer(
            embedding_model,
            cache_folder=cache_dir
        )

        # 集合
        self.collections = {
            "user_profiles": None,
            "conversations": None,
            "knowledge_base": None
        }

        self._init_collections()

    def _init_collections(self):
        """初始化集合"""
        for name in self.collections.keys():
            try:
                # 创建或获取集合
                collection = self.client.get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"}
                )
                self.collections[name] = collection
                print(f"✅ Collection '{name}' ready")
            except Exception as e:
                print(f"❌ Failed to init collection '{name}': {e}")

    def add_conversation(
        self,
        session_id: str,
        user_input: str,
        ai_response: str,
        metadata: Optional[Dict] = None
    ):
        """添加对话到向量存储"""
        text = f"User: {user_input}\nAI: {ai_response}"

        # 生成嵌入
        embedding = self.embedding_model.encode(text).tolist()

        # 存储到conversations集合
        self.collections["conversations"].add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[{
                "session_id": session_id,
                "timestamp": str(datetime.now()),
                **(metadata or {})
            }],
            ids=[f"{session_id}_{datetime.now().timestamp()}"]
        )

    def search_relevant_context(
        self,
        query: str,
        session_id: str,
        n_results: int = 3
    ) -> List[str]:
        """搜索相关上下文"""
        # 生成查询嵌入
        query_embedding = self.embedding_model.encode(query).tolist()

        # 搜索
        results = self.collections["conversations"].query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"session_id": session_id}
        )

        return results["documents"][0] if results["documents"] else []

    def build_user_profile(
        self,
        session_id: str,
        preferences: Dict[str, Any]
    ):
        """构建用户画像"""
        profile_text = f"""
        用户偏好总结：
        {', '.join(f'{k}: {v}' for k, v in preferences.items())}
        """

        embedding = self.embedding_model.encode(profile_text).tolist()

        self.collections["user_profiles"].add(
            documents=[profile_text],
            embeddings=[embedding],
            metadatas=[{"session_id": session_id, **preferences}],
            ids=[f"profile_{session_id}"]
        )
```

#### 3. 集成到记忆系统

修改 `src/anima/memory_db/memory_system.py`:
```python
from .vector_store import VectorStore

class MemorySystem:
    def __init__(self, config: Dict):
        # ... 现有代码 ...

        # 初始化向量存储
        self.vector_store = VectorStore(
            storage_path="E:/AnimaData/vector_db"
        )

    async def retrieve_context(
        self,
        query: str,
        session_id: str,
        max_turns: int = 5
    ) -> List[MemoryTurn]:
        """检索相关记忆（增强版：向量搜索 + 关键词搜索）"""
        results = []

        # 1. 短期记忆
        recent = await self.short_term.get_recent(session_id, max_turns)
        results.extend(recent)

        # 2. 向量搜索（语义相关）
        try:
            relevant_docs = self.vector_store.search_relevant_context(
                query=query,
                session_id=session_id,
                n_results=3
            )
            # 将文档转换为MemoryTurn...
        except Exception as e:
            logger.warning(f"向量搜索失败: {e}")

        # 3. 去重
        return self._deduplicate(results)
```

### 成本估算

**E盘空间需求**:
- 向量数据: ~100KB / 1000条对话
- 嵌入模型: ~400MB (sentence-transformers)
- 10万条对话: ~10MB向量数据

**结论**: 即使是机械硬盘，完全够用！

---

## 🔧 第三层：本地模型微调 (可选)

### 为什么可选？

- 前两层已经能获得很好的个性化效果
- 微调需要大量GPU时间和数据
- 效果提升可能有限（10-20%）

### 何时考虑微调？

- ✅ 前两层效果不够好
- ✅ 有大量领域数据（>10K条对话）
- ✅ 需要特定的说话风格或知识

### 技术方案

#### 1. 模型选择

**推荐模型** (适合5090):

| 模型 | 参数量 | 显存需求 | 微调时间 | 推荐度 |
|------|--------|----------|----------|--------|
| Qwen2.5-7B | 7B | ~16GB | 2-4小时 | ⭐⭐⭐⭐⭐ |
| Qwen2.5-14B | 14B | ~24GB | 4-8小时 | ⭐⭐⭐⭐ |
| Llama-3.1-8B | 8B | ~18GB | 3-5小时 | ⭐⭐⭐⭐ |
| GLM-4-9B | 9B | ~20GB | 3-6小时 | ⭐⭐⭐⭐⭐ (中文) |

**推荐**: Qwen2.5-7B 或 GLM-4-9B（中文优化）

#### 2. 微调方法

**LoRA微调** (推荐):
- 参数高效：只训练1-3%的参数
- 显存友好：7B模型只需~12GB
- 保存方便：LoRA权重只有几十MB

**工具选择**:
1. **LLaMA-Factory** (推荐，易用)
2. **Unsloth** (最快)
3. **Axolotl** (灵活)

#### 3. 实施步骤

##### 安装LLaMA-Factory

```bash
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -r requirements.txt
```

##### 准备训练数据

**文件**: `E:/AnimaData/training_data.jsonl`
```jsonl
{"instruction": "你是个活泼的AI少女", "input": "今天天气不错", "output": "是呀是呀！阳光明媚的好天气呢！要不要出去走走？"}
{"instruction": "你是个活泼的AI少女", "input": "我心情不好", "output": "诶？怎么啦？发生什么事了吗？别难过，我会陪着你的..."}
{"instruction": "你是个活泼的AI少女", "input": "你喜欢什么", "output": "嗯...我喜欢奶茶！还有猫咪！你也喜欢这些吗？"}
```

##### 配置微调

**文件**: `llama_factory_config.yaml`
```yaml
### 模型
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
trust_remote_code: true

### 方法
finetuning_type: lora
lora_target: all
lora_rank: 8
lora_alpha: 16

### 数据
dataset: xiaoya_conversations
dataset_dir: E:/AnimaData/training_data
template: qwen
cutoff_len: 512
max_samples: 1000
overwrite_cache: true
preprocessing_num_workers: 16

### 输出
output_dir: E:/AnimaData/model_ckpt/qwen2.5-7b-xiaoya
logging_steps: 10
save_steps: 100
plot_loss: true
overwrite_output_dir: true

### 训练
per_device_train_batch_size: 2
gradient_accumulation_steps: 8
learning_rate: 5.0e-5
num_train_epochs: 3
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true
ddp_timeout: 180000000

### 评估
val_size: 0.1
per_device_eval_batch_size: 1
eval_strategy: steps
eval_steps: 100
```

##### 开始训练

```bash
llamafactory-cli train llama_factory_config.yaml
```

##### 合并模型

```bash
llamafactory-cli export \
    --model_name_or_path Qwen/Qwen2.5-7B-Instruct \
    --adapter_name_or_path E:/AnimaData/model_ckpt/qwen2.5-7b-xiaoya \
    --template qwen \
    --finetuning_type lora \
    --export_dir E:/AnimaData/model_ckpt/qwen2.5-7b-xiaoya-merged \
    --export_size 2 \
    --export_device cpu
```

##### 使用微调后的模型

修改 `config/services/llm/ollama.yaml`:
```yaml
llm_config:
  type: ollama
  model: qwen2.5-7b-xiaoya-merged
  base_url: http://localhost:11434
```

或使用llama.cpp部署:
```bash
# 转换为GGUF
quantize E:/AnimaData/model_ckpt/qwen2.5-7b-xiaoya-merged \
    E:/AnimaData/model_ckpt/qwen2.5-7b-xiaoya-Q4_K_M.gguf \
    Q4_K_M

# 运行Ollama
ollama create qwen-xiaoya -f Modelfile
ollama run qwen-xiaoya
```

### 硬件需求

**RTX 5090 D (假设32GB显存)**:
- ✅ 7B模型微调: 游刃有余
- ✅ 14B模型微调: 完全可行
- ⚠️ 32B模型微调: 需要梯度检查点

**E盘空间**:
- 模型权重: ~14GB (7B) / ~28GB (14B)
- 训练数据: ~100MB
- 检查点: ~30GB
- **总计**: ~50-70GB（完全够用）

---

## 🚀 第四层：实时上下文增强

### 动态用户画像

**功能**: 实时学习用户偏好，动态调整回复风格

**实现**:

**文件**: `src/anima/memory_db/user_profile.py`

```python
"""
用户画像系统
动态学习用户偏好
"""

from typing import Dict, List, Any
from collections import defaultdict
import json


class UserProfile:
    """用户画像"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.profile = {
            "name": None,
            "preferences": defaultdict(int),  # 偏好统计
            "topics": defaultdict(int),  # 话题统计
            "emotion_history": [],  # 情感历史
            "interaction_style": {  # 互动风格
                "message_length": [],
                "response_time": [],
                "emoji_usage": []
            }
        }

    def update_from_conversation(
        self,
        user_input: str,
        ai_response: str,
        emotions: List[str]
    ):
        """从对话中更新画像"""
        # 更新情感历史
        self.profile["emotion_history"].extend(emotions)

        # 统计消息长度
        self.profile["interaction_style"]["message_length"].append(
            len(user_input)
        )

        # 提取关键词（简单实现）
        keywords = self._extract_keywords(user_input)
        for keyword in keywords:
            self.profile["topics"][keyword] += 1

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单实现：分词 + 过滤停用词
        # 实际应该用jieba或更复杂的NLP
        words = text.split()
        stop_words = {"的", "了", "是", "在", "我", "你"}
        return [w for w in words if len(w) > 1 and w not in stop_words]

    def get_summary(self) -> str:
        """获取画像摘要"""
        parts = []

        if self.profile["name"]:
            parts.append(f"用户名字：{self.profile['name']}")

        # 常聊话题
        top_topics = sorted(
            self.profile["topics"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        if top_topics:
            parts.append(f"常聊话题：{', '.join(t[0] for t in top_topics)}")

        # 互动风格
        avg_length = sum(self.profile["interaction_style"]["message_length"]) / len(
            self.profile["interaction_style"]["message_length"]
        ) if self.profile["interaction_style"]["message_length"] else 0

        if avg_length > 50:
            parts.append("用户喜欢详细表达")
        else:
            parts.append("用户喜欢简洁交流")

        return "\n".join(parts)

    def save(self, path: str):
        """保存画像到文件"""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.profile, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, session_id: str, path: str) -> "UserProfile":
        """从文件加载画像"""
        profile = cls(session_id)
        with open(path, 'r', encoding='utf-8') as f:
            profile.profile = json.load(f)
        return profile
```

### 集成到编排器

修改 `src/anima/services/conversation/orchestrator.py`:
```python
class ConversationOrchestrator:
    def __init__(self, ..., user_profile=None):
        # ... 现有代码 ...
        self.user_profile = user_profile or UserProfile(session_id)

    async def _process_conversation(self, ctx, text):
        # ... 获取用户画像摘要 ...
        profile_summary = self.user_profile.get_summary()

        # 注入到输入文本
        text = f"{profile_summary}\n\n当前对话：{text}"

        # ... 处理对话 ...

        # 更新用户画像
        self.user_profile.update_from_conversation(
            original_text,
            response_text,
            emotions
        )
```

---

## 📊 效果对比

| 层次 | 实施难度 | 效果提升 | 时间投入 | 推荐优先级 |
|------|----------|----------|----------|------------|
| 第一层：人设定义 | ⭐ | ⭐⭐⭐ | 1-2小时 | 🔥 必须做 |
| 第二层：RAG+记忆 | ⭐⭐ | ⭐⭐⭐⭐ | 1-2天 | 🔥 强烈推荐 |
| 第三层：模型微调 | ⭐⭐⭐⭐ | ⭐⭐⭐ | 3-7天 | ⚠️ 可选 |
| 第四层：实时增强 | ⭐⭐⭐ | ⭐⭐⭐⭐ | 2-3天 | ✅ 推荐 |

**推荐路径**:
1. ✅ 第一层 (立即可用)
2. ✅ 第二层 (1-2周内完成)
3. ✅ 第四层 (2-4周内完成)
4. ⚠️ 第三层 (根据效果决定是否需要)

---

## 🛠️ 快速开始

### 方案A：快速体验 (1小时内)

**只使用第一层**:
```bash
# 1. 切换人设
vim config/config.yaml  # 修改 persona: "xiaoya"

# 2. 重启服务
python -m anima.socketio_server

# 3. 对话测试
# 你会立即感受到鲜明的性格差异！
```

### 方案B：完整体验 (1-2周)

**实施第一+二+四层**:
```bash
# Week 1: 第一层 + 第二层
# Day 1-2: 安装ChromaDB，实现向量存储
# Day 3-4: 集成到记忆系统
# Day 5-7: 测试和调优

# Week 2: 第四层
# Day 1-2: 实现用户画像
# Day 3-4: 集成到编排器
# Day 5-7: 完整测试
```

### 方案C：终极定制 (1-2月)

**全部四层**:
```bash
# 先完成方案B
# 再花3-4周进行模型微调
# 需要准备至少1000条高质量对话数据
```

---

## 📈 预期效果

### 第一层后
- ✅ AI有鲜明性格和说话风格
- ✅ 情感表达丰富
- ✅ 回复具有一致性

### 第二层后
- ✅ AI记住你的喜好
- ✅ 能联系之前的对话
- ✅ 语义相关检索

### 第四层后
- ✅ AI主动学习你的习惯
- ✅ 回复风格逐渐适应你
- ✅ 个性化越来越强

### 第三层后
- ✅ 说话风格高度一致
- ✅ 专业知识融入
- ✅ 10-20%效果提升

---

## 🎁 额外建议

### 数据备份

**重要**: 定期备份E盘数据！
```bash
# 每周备份
robocopy E:/AnimaData D:/Backup/AnimaData /MIR

# 或使用专用备份工具
```

### 性能优化

**如果E盘机械硬盘太慢**:
1. **建议**: 买个SSD（500GB只要200-300元）
2. **性价比**: 极大提升体验
3. **缓存策略**: 热数据放内存/C盘，冷数据放E盘

### 监控和日志

```python
# 记录个性化效果
import logging

logger = logging.getLogger("personalization")
logger.info(f"User profile updated: {session_id}")
logger.info(f"Memory retrieved: {len(memories)} items")
logger.info(f"Response time: {response_time}s")
```

---

## 🤝 需要帮助？

实施过程中遇到问题？：

1. **第一层问题**: 查看人设文件是否正确加载
2. **第二层问题**: 检查ChromaDB路径和模型下载
3. **第四层问题**: 调试用户画像更新逻辑
4. **第三层问题**: 确认GPU显存和数据格式

**调试技巧**:
```python
# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 检查向量存储
print(vector_store.collections["conversations"].count())

# 测试嵌入
embedding = vector_store.embedding_model.encode("测试文本")
print(embedding.shape)
```

---

**祝你成功打造独一无二的AI VTuber！** 🎉

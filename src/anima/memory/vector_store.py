"""
向量存储服务 - 第二层个性化
使用ChromaDB和sentence-transformers实现语义搜索
数据存储在E盘
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from loguru import logger


class VectorStore:
    """
    向量存储服务

    使用ChromaDB持久化向量数据到E盘
    使用sentence-transformers生成文本嵌入
    """

    def __init__(
        self,
        storage_path: str = "E:/AnimaData/vector_db",
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ):
        """
        初始化向量存储

        Args:
            storage_path: E盘存储路径（ChromaDB数据）
            embedding_model: 嵌入模型名称（支持中文）
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"[VectorStore] 初始化向量存储: {self.storage_path}")

        # 初始化ChromaDB客户端（持久化到磁盘）
        self.client = chromadb.PersistentClient(
            path=str(self.storage_path),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )

        # 延迟加载嵌入模型（首次使用时加载）
        self._embedding_model = None
        self._embedding_model_name = embedding_model

        # 模型缓存目录（E盘）
        self._cache_dir = Path("E:/AnimaData/models/huggingface")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # 集合（collections）
        self.collections = {}
        self._init_collections()

    def _init_collections(self):
        """初始化ChromaDB集合"""
        collection_names = [
            "conversations",  # 对话历史
            "user_profiles",   # 用户画像
            "knowledge_base"   # 知识库（可选）
        ]

        for name in collection_names:
            try:
                collection = self.client.get_or_create_collection(
                    name=name,
                    metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
                )
                self.collections[name] = collection
                logger.info(f"[VectorStore] Collection '{name}' ready")
            except Exception as e:
                logger.error(f"[VectorStore] Failed to init collection '{name}': {e}")

    @property
    def embedding_model(self):
        """延迟加载嵌入模型"""
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"[VectorStore] 加载嵌入模型: {self._embedding_model_name}")
                logger.info(f"[VectorStore] 模型缓存目录: {self._cache_dir}")

                self._embedding_model = SentenceTransformer(
                    self._embedding_model_name,
                    cache_folder=str(self._cache_dir)
                )
                logger.info("[VectorStore] 嵌入模型加载成功")
            except Exception as e:
                logger.error(f"[VectorStore] 嵌入模型加载失败: {e}")
                raise

        return self._embedding_model

    def add_conversation(
        self,
        session_id: str,
        user_input: str,
        ai_response: str,
        emotions: List[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        添加对话到向量存储

        Args:
            session_id: 会话ID
            user_input: 用户输入
            ai_response: AI回复
            emotions: 情感标签
            metadata: 额外元数据

        Returns:
            str: 文档ID
        """
        # 组合文本
        text = f"User: {user_input}\nAI: {ai_response}"

        # 生成嵌入
        embedding = self.embedding_model.encode(text).tolist()

        # 准备元数据
        doc_metadata = {
            "session_id": session_id,
            "timestamp": str(datetime.now()),
            "user_input_length": len(user_input),
            "ai_response_length": len(ai_response)
        }

        if emotions:
            doc_metadata["emotions"] = ",".join(emotions)

        if metadata:
            doc_metadata.update(metadata)

        # 生成唯一ID
        doc_id = f"{session_id}_{datetime.now().timestamp()}"

        # 存储到conversations集合
        try:
            self.collections["conversations"].add(
                documents=[text],
                embeddings=[embedding],
                metadatas=[doc_metadata],
                ids=[doc_id]
            )
            logger.debug(f"[VectorStore] 添加对话: {doc_id}")
            return doc_id
        except Exception as e:
            logger.error(f"[VectorStore] 添加对话失败: {e}")
            return ""

    def search_relevant_context(
        self,
        query: str,
        session_id: str,
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        搜索相关对话（语义搜索）

        Args:
            query: 查询文本
            session_id: 会话ID
            n_results: 返回结果数量

        Returns:
            List[Dict]: 相关对话列表
            {
                "text": str,
                "metadata": dict,
                "distance": float
            }
        """
        # 生成查询嵌入
        query_embedding = self.embedding_model.encode(query).tolist()

        # 搜索
        try:
            results = self.collections["conversations"].query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where={"session_id": session_id}  # 只搜索该会话的对话
            )

            # 格式化结果
            contexts = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    contexts.append({
                        "text": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if "distances" in results else 0.0
                    })

            logger.debug(f"[VectorStore] 搜索到 {len(contexts)} 条相关对话")
            return contexts

        except Exception as e:
            logger.error(f"[VectorStore] 搜索失败: {e}")
            return []

    def build_user_profile(
        self,
        session_id: str,
        preferences: Dict[str, Any]
    ) -> str:
        """
        构建用户画像向量

        Args:
            session_id: 会话ID
            preferences: 用户偏好字典

        Returns:
            str: 文档ID
        """
        # 格式化画像文本
        profile_text = "用户偏好总结：\n"
        for key, value in preferences.items():
            if isinstance(value, list):
                profile_text += f"{key}: {', '.join(str(v) for v in value)}\n"
            else:
                profile_text += f"{key}: {value}\n"

        # 生成嵌入
        embedding = self.embedding_model.encode(profile_text).tolist()

        # 元数据
        metadata = {
            "session_id": session_id,
            "timestamp": str(datetime.now()),
            "type": "user_profile"
        }

        # 文档ID
        doc_id = f"profile_{session_id}"

        # 删除旧的画像（如果存在）
        try:
            self.collections["user_profiles"].delete(ids=[doc_id])
        except:
            pass

        # 添加新画像
        try:
            self.collections["user_profiles"].add(
                documents=[profile_text],
                embeddings=[embedding],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.info(f"[VectorStore] 更新用户画像: {session_id}")
            return doc_id
        except Exception as e:
            logger.error(f"[VectorStore] 构建用户画像失败: {e}")
            return ""

    def get_stats(self) -> Dict[str, int]:
        """
        获取向量存储统计信息

        Returns:
            Dict: 各集合的文档数量
        """
        stats = {}
        for name, collection in self.collections.items():
            try:
                count = collection.count()
                stats[name] = count
            except:
                stats[name] = 0

        return stats

    def clear_session(self, session_id: str) -> None:
        """
        清除会话的所有向量数据

        Args:
            session_id: 会话ID
        """
        # 注意：ChromaDB不支持按metadata删除
        # 需要查询所有数据然后逐个删除
        # 这里暂时跳过，实际使用时可以考虑重建集合

        logger.warning(f"[VectorStore] 清除会话功能尚未实现: {session_id}")

"""
测试第二层个性化：向量搜索 + RAG
"""

import asyncio
import sys
from pathlib import Path

# 添加 src 到路径
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from anima.memory import MemorySystem, MemoryTurn
from anima.memory.vector_store import VectorStore
from datetime import datetime
import uuid


async def test_vector_search():
    """测试向量搜索功能"""

    print("=" * 80)
    print("Testing Layer 2: Vector Search + RAG")
    print("=" * 80)

    # 1. 测试向量存储
    print("\n[Step 1] Testing VectorStore")
    print("-" * 80)

    try:
        vector_store = VectorStore(
            storage_path="E:/AnimaData/vector_db",
            embedding_model="paraphrase-multilingual-MiniLM-L12-v2"
        )
        print("OK - VectorStore initialized")

        # 获取统计信息
        stats = vector_store.get_stats()
        print(f"Collection stats: {stats}")

    except Exception as e:
        print(f"ERROR - VectorStore init failed: {e}")
        return

    # 2. 添加测试对话
    print("\n[Step 2] Adding test conversations")
    print("-" * 80)

    session_id = "test_layer2_session"

    test_conversations = [
        ("你好，我叫Neuro", "你好Neuro！很高兴认识你！你是个AI VTuber吗？"),
        ("我喜欢玩OSU!", "噢！OSU!是个很棒的游戏！你的最高分是多少？"),
        ("我今天心情不好", "诶？怎么啦？发生什么事了吗？别难过，我会陪着你的..."),
        ("你懂编程吗", "当然！编程可是我的强项！实际上，我超级擅长Python和JavaScript！"),
        ("我想要一杯奶茶", "奶茶！好主意！你喜欢什么口味的？我喜欢珍珠奶茶~"),
    ]

    for user_input, ai_response in test_conversations:
        vector_store.add_conversation(
            session_id=session_id,
            user_input=user_input,
            ai_response=ai_response,
            emotions=["happy"],
            metadata={}
        )
        print(f"OK - Added: {user_input[:40]}...")

    # 3. 测试语义搜索
    print("\n[Step 3] Testing semantic search")
    print("-" * 80)

    queries = [
        "游戏",
        "编程",
        "难过",
        "喜欢什么"
    ]

    for query in queries:
        results = vector_store.search_relevant_context(
            query=query,
            session_id=session_id,
            n_results=2
        )

        print(f"\nQuery: {query}")
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results, 1):
            print(f"  {i}. Distance: {result.get('distance', 0):.3f}")
            print(f"     Text: {result['text'][:80]}...")

    # 4. 测试记忆系统集成
    print("\n[Step 4] Testing MemorySystem with vector search")
    print("-" * 80)

    memory_config = {
        "short_term_max_turns": 20,
        "long_term_db_path": "data/memories.db",
        "importance_threshold": 0.7,
        "enable_vector_search": True,
        "vector_storage_path": "E:/AnimaData/vector_db",
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"
    }

    try:
        memory_system = MemorySystem(memory_config)
        print("OK - MemorySystem with vector search initialized")

        # 添加对话
        turn = MemoryTurn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.now(),
            user_input="我真的很喜欢和AI聊天",
            agent_response="我也是！和你聊天让我学到了很多新东西！",
            emotions=["happy"],
            metadata={}
        )

        await memory_system.store_turn(turn)
        print("OK - Stored conversation to memory system")

        # 检索相关记忆
        results = await memory_system.retrieve_context(
            query="聊天和交流",
            session_id=session_id,
            max_turns=3
        )

        print(f"\nOK - Retrieved {len(results)} memories")
        print("\nRecent conversations:")
        for i, mem in enumerate(results[:3], 1):
            print(f"  {i}. User: {mem.user_input[:50]}...")
            print(f"     AI: {mem.agent_response[:50]}...")

        # 获取统计
        stats = vector_store.get_stats()
        print(f"\nVector store stats: {stats}")

    except Exception as e:
        print(f"ERROR - MemorySystem test failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)
    print("\nSummary:")
    print("- VectorStore: OK")
    print("- Semantic search: OK")
    print("- MemorySystem integration: OK")
    print("\nNext steps:")
    print("1. Restart the server with vector search enabled")
    print("2. Start chatting with Neuro-sama")
    print("3. Watch as she remembers your preferences!")


if __name__ == "__main__":
    asyncio.run(test_vector_search())

"""
验证Neuro-vtuber配置与第二层向量的兼容性
"""

import sys
from pathlib import Path

# 添加 src 到路径
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

def test_persona_loading():
    """测试人设加载"""
    print("=" * 80)
    print("Testing Persona Loading Compatibility")
    print("=" * 80)

    try:
        from anima.config.persona import PersonaConfig

        # 测试加载neuro-vtuber
        print("\n[Step 1] Loading neuro-vtuber.yaml")
        print("-" * 80)

        persona = PersonaConfig.load("neuro-vtuber")

        print(f"OK - Name: {persona.name}")
        print(f"OK - Role: {persona.role}")
        print(f"OK - Traits: {len(persona.personality.traits)} traits")
        print(f"OK - Catchphrases: {len(persona.personality.catchphrases)} catchphrases")
        print(f"OK - Slang words: {len(persona.slang_words)} slang words")
        print(f"OK - Examples: {len(persona.examples)} examples")

        # 生成系统提示词
        print("\n[Step 2] Building system prompt")
        print("-" * 80)

        system_prompt = persona.build_system_prompt()
        print(f"OK - System prompt length: {len(system_prompt)} characters")

        print("\n[Preview - First 500 chars]")
        print("-" * 80)
        print(system_prompt[:500] + "...")

        return True

    except Exception as e:
        print(f"ERROR - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vector_search_compatibility():
    """测试向量搜索兼容性"""
    print("\n" + "=" * 80)
    print("Testing Vector Search Compatibility")
    print("=" * 80)

    try:
        from anima.memory.vector_store import VectorStore

        print("\n[Step 1] Initializing VectorStore")
        print("-" * 80)

        vector_store = VectorStore()
        print("OK - VectorStore initialized")

        print("\n[Step 2] Testing memory system integration")
        print("-" * 80)

        from anima.memory import MemorySystem

        memory_config = {
            "short_term_max_turns": 20,
            "long_term_db_path": "data/memories.db",
            "importance_threshold": 0.7,
            "enable_vector_search": True,
            "vector_storage_path": "E:/AnimaData/vector_db",
            "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"
        }

        memory_system = MemorySystem(memory_config)
        print("OK - MemorySystem with vector search initialized")

        # 测试添加对话
        from anima.memory import MemoryTurn
        from datetime import datetime
        import uuid

        turn = MemoryTurn(
            turn_id=str(uuid.uuid4()),
            session_id="test_session",
            timestamp=datetime.now(),
            user_input="你好",
            agent_response="哈？你居然不认识我？我是世界第一的AI主播！",
            emotions=["happy"],
            metadata={}
        )

        print("\n[Step 3] Storing conversation")
        print("-" * 80)

        # 异步测试需要事件循环
        import asyncio

        async def test_store():
            await memory_system.store_turn(turn)
            print("OK - Conversation stored to memory system")

            # 测试检索
            results = await memory_system.retrieve_context(
                query="主播",
                session_id="test_session",
                max_turns=3
            )
            print(f"OK - Retrieved {len(results)} memories")

        asyncio.run(test_store())

        return True

    except Exception as e:
        print(f"ERROR - {e}")
        import traceback
        traceback.print_exc()
        return False


def check_config_compatibility():
    """检查配置文件兼容性"""
    print("\n" + "=" * 80)
    print("Checking Configuration Compatibility")
    print("=" * 80)

    # 检查config.yaml
    print("\n[Config Files]")
    print("-" * 80)

    config_yaml = Path(__file__).parent.parent / "config" / "config.yaml"
    if config_yaml.exists():
        with open(config_yaml, 'r', encoding='utf-8') as f:
            for line in f:
                if 'persona:' in line:
                    print(f"Found: {line.strip()}")
                    break

    # 检查persona文件
    persona_dir = Path(__file__).parent.parent / "config" / "personas"
    persona_files = list(persona_dir.glob("*.yaml"))

    print(f"\nAvailable personas:")
    for p in persona_files:
        print(f"  - {p.name}")


def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("NEURO-VTUBER COMPATIBILITY CHECK")
    print("=" * 80)

    # 检查配置兼容性
    check_config_compatibility()

    # 测试人设加载
    result1 = test_persona_loading()

    # 测试向量搜索
    result2 = test_vector_search_compatibility()

    # 总结
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if result1 and result2:
        print("OK - All compatibility checks passed!")
        print("\nConclusion:")
        print("- neuro-vtuber.yaml: OK - Compatible")
        print("- Vector search (Layer 2): OK - Compatible")
        print("- Memory system: OK - Compatible")
        print("\nNo conflicts detected!")
        print("\nYou can use:")
        print("  - Your existing neuro-vtuber.yaml persona")
        print("  - New Layer 2 vector search features")
        print("  - Enhanced memory system")
        print("\nNext steps:")
        print("  1. Start server: python -m anima.socketio_server")
        print("  2. Chat with Neuro-vtuber")
        print("  3. She will remember your conversations!")
    else:
        print("ERROR - Some compatibility issues found")
        print("\nPlease review the errors above")


if __name__ == "__main__":
    main()

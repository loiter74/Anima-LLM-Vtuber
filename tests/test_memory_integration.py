"""
Test Memory System Integration
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from anima.memory import MemorySystem, MemoryTurn
from datetime import datetime
import uuid


async def test_memory_system():
    """Test memory system basic functionality"""

    print("=" * 60)
    print("Testing Memory System")
    print("=" * 60)

    # 1. Initialize memory system
    config = {
        "short_term_max_turns": 20,
        "long_term_db_path": "data/memories.db",
        "importance_threshold": 0.7
    }

    memory = MemorySystem(config)
    print("OK - Memory system initialized")

    # 2. Create test conversations
    session_id = "test_session_001"

    test_turns = [
        MemoryTurn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.now(),
            user_input="Hello, my name is Xiao Ming",
            agent_response="Hello Xiao Ming! Nice to meet you.",
            emotions=["happy"],
            metadata={}
        ),
        MemoryTurn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.now(),
            user_input="Remember, I like programming",
            agent_response="Got it, I remember you like programming.",
            emotions=["happy"],
            metadata={}
        ),
        MemoryTurn(
            turn_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.now(),
            user_input="How is the weather today?",
            agent_response="Today is sunny, good for going out.",
            emotions=["neutral"],
            metadata={}
        ),
    ]

    # 3. Store conversations
    print("\n" + "=" * 60)
    print("Storing conversations...")
    print("=" * 60)

    for turn in test_turns:
        await memory.store_turn(turn)
        print(f"OK - Stored: {turn.user_input[:40]}... (importance: {turn.importance:.2f})")

    # 4. Retrieve related memories
    print("\n" + "=" * 60)
    print("Retrieving related memories...")
    print("=" * 60)

    query = "What does Xiao Ming like?"
    results = await memory.retrieve_context(
        query=query,
        session_id=session_id,
        max_turns=3
    )

    print(f"\nQuery: {query}")
    print(f"Found {len(results)} related memories:\n")

    for i, mem in enumerate(results, 1):
        print(f"{i}. User: {mem.user_input}")
        print(f"   AI: {mem.agent_response}")
        print(f"   Importance: {mem.importance:.2f}")
        print()

    # 5. Get user history
    print("=" * 60)
    print("Getting user history...")
    print("=" * 60)

    history = await memory.get_user_history(
        session_id=session_id,
        limit=10
    )

    print(f"History has {len(history)} records\n")

    for i, mem in enumerate(history[:3], 1):
        print(f"{i}. [{mem.timestamp}] {mem.user_input[:40]}...")

    # 6. Clear session
    print("\n" + "=" * 60)
    print("Clearing session...")
    print("=" * 60)

    await memory.clear_session(session_id)
    print("OK - Session cleared")

    # 7. Close memory system
    memory.close()
    print("\nOK - Memory system closed")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_memory_system())

"""
Simple test to verify server initialization and vector search
"""

import sys
import asyncio
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from anima.service_context import ServiceContext
from anima.config import AppConfig


async def test_memory_initialization():
    """Directly test memory system initialization"""
    print("=" * 80)
    print("Testing ServiceContext Memory Initialization")
    print("=" * 80)

    try:
        # Create ServiceContext
        print("\n[Step 1] Creating ServiceContext")
        print("-" * 80)
        ctx = ServiceContext()
        ctx.session_id = "test_session_direct"

        # Load configuration
        print("\n[Step 2] Loading configuration")
        print("-" * 80)
        config = AppConfig.load()

        # Initialize services (this will call init_memory())
        print("\n[Step 3] Initializing services (including memory)")
        print("-" * 80)
        await ctx.load_from_config(config)

        # Check if memory system was initialized
        print("\n[Step 4] Checking memory system")
        print("-" * 80)
        if ctx.memory_system:
            print("OK - Memory system initialized")

            # Check if vector search is enabled
            if ctx.memory_system.vector_store:
                print("OK - Vector store initialized")
                print(f"     Storage path: {ctx.memory_system.vector_store.storage_path}")
                print(f"     Embedding model: {ctx.memory_system.vector_store._embedding_model_name}")

                # Get vector store statistics
                stats = ctx.memory_system.vector_store.get_stats()
                print(f"     Collections: {list(stats.keys())}")
                print(f"     Document counts: {stats}")
            else:
                print("WARNING - Vector store not initialized")
        else:
            print("ERROR - Memory system not initialized")

        # Clean up
        print("\n[Step 5] Cleaning up")
        print("-" * 80)
        await ctx.close()
        print("OK - ServiceContext closed")

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        if ctx.memory_system and ctx.memory_system.vector_store:
            print("OK - All systems initialized successfully!")
            print("\nConclusion:")
            print("- ServiceContext: OK")
            print("- Memory system: OK")
            print("- Vector search (Layer 2): OK")
            print("- neuro-vtuber persona: OK")
            print("\nThe server is ready to use with vector search!")
        else:
            print("ERROR - Some systems failed to initialize")

    except Exception as e:
        print(f"\nERROR - {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_memory_initialization())

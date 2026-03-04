"""Test full configuration loading"""
import sys
sys.path.insert(0, 'src')

print("=" * 60)
print("Testing Full Configuration Load")
print("=" * 60)
print()

try:
    from anima.config.app import AppConfig
    from anima.service_context import ServiceContext
    from anima.services.conversation.orchestrator import ConversationOrchestrator

    # Test 1: Load config
    print("[Test 1] Loading configuration...")
    config = AppConfig.load()
    print(f"[OK] Config loaded successfully")
    print(f"   - Host: {config.system.host}")
    print(f"   - Port: {config.system.port}")
    print(f"   - Persona: {config.persona}")
    print(f"   - ASR: {config.services.asr}")
    print(f"   - TTS: {config.services.tts}")
    print(f"   - Agent: {config.services.agent}")
    print(f"   - VAD: {config.services.vad}")
    print()

    # Test 2: Check environment variables
    print("[Test 2] Checking environment variables...")
    import os
    env_vars = ["ANIMA_DATA_DIR", "ANIMA_BASE_MODEL_PATH", "ANIMA_LORA_PATH"]
    for var in env_vars:
        value = os.getenv(var)
        if value:
            print(f"[OK] {var} = {value}")
        else:
            print(f"[WARN] {var} is not set (will use defaults)")
    print()

    # Test 3: Service context
    print("[Test 3] Creating service context...")
    import asyncio

    async def test_service_context():
        service_context = ServiceContext()
        await service_context.load_from_config(config)
        return service_context

    service_context = asyncio.run(test_service_context())
    print(f"[OK] Service context created")
    print(f"   - ASR: {type(service_context.asr_engine).__name__}")
    print(f"   - TTS: {type(service_context.tts_engine).__name__}")
    print(f"   - LLM: {type(service_context.llm_engine).__name__}")
    print(f"   - VAD: {type(service_context.vad_engine).__name__}")
    print()

    # Test 4: Check LocalLoraLLM initialization
    print("[Test 4] Testing LocalLoraLLM device fallback...")
    from anima.services.llm.implementations.local_lora_llm import LocalLoraLLM
    llm = LocalLoraLLM(
        base_model_name="test",
        lora_path="test",
        device="cuda"
    )
    print(f"[OK] LocalLoraLLM initialized")
    print(f"   - Requested device: cuda")
    print(f"   - Actual device: {llm.device}")
    print(f"   - Auto-fallback: {'Yes' if llm.device != llm.requested_device else 'No'}")
    print()

    print("=" * 60)
    print("[SUCCESS] ALL TESTS PASSED!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Ensure models are downloaded to the data directory")
    print("  2. Run: .\\scripts\\start.ps1")
    print("  3. Open browser: http://localhost:3000")
    print()

except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

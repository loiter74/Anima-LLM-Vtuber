# 全面债务清除 + LivingMemory V2 集成实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire LivingMemorySystem V2 into LangGraph orchestration, purge all legacy memory debt, fix 931 test `$$$` placeholders, and remediate source-level NameError bugs — zero backward compatibility.

**Architecture:** 4 sequential phases. Phase 1 (LangGraph integration) modifies 6 orchestration files. Phase 2 (legacy purge) moves 30+ old modules to `_legacy/`. Phase 3 (test cleanup) batch-fixes 120 test files. Phase 4 (NameError remediation) fixes remaining runtime import issues. Each phase is independently committable.

**Tech Stack:** Python 3.13+, LangGraph, ast-grep for batch refactoring, pytest asyncio

---

## Phase 1: V2 LangGraph Integration

### Task 1.1: Update AgentState — remove old memory fields, add emotion_vad

**Files:**
- Modify: `src/animetta/orchestration/graph/state.py`

**Step 1: Read current state.py around the memory fields**

```bash
grep -n "fuzzy_memories\|injection_tier\|user_query_depth\|meme_candidates\|meme_injected\|emotion" src/animetta/orchestration/graph/state.py
```

**Step 2: Remove old memory fields, add emotion_vad**

Remove lines containing:
- `fuzzy_memories: List[str]`
- `injection_tier: int`
- `user_query_depth: int`
- `meme_candidates: List[Dict[str, Any]]`
- `meme_injected: bool`

Add after `emotion: Optional[str]`:
```python
    emotion_vad: Optional[tuple[float, float, float]]  # VAD emotion vector from emotion_node
```

**Step 3: Verify state.py imports still work**

Run: `PYTHONPATH=src python -c "from animetta.orchestration.graph.state import AgentState; print('OK')"`
Expected: OK (no errors)

**Step 4: Commit**

```bash
git add src/animetta/orchestration/graph/state.py
git commit -m "refactor(state): remove old memory fields, add emotion_vad for V2"
```

---

### Task 1.2: Update emotion_node — discrete emotion → VAD vector

**Files:**
- Modify: `src/animetta/orchestration/graph/emotion_node.py`

**Step 1: Read current emotion_node.py**

**Step 2: Add VAD conversion before return**

Find the `return {"emotion": ...}` in `emotion_node()`. Before it, add:
```python
from animetta.memory.v2.emotion_field import VAD_MAP
vad = VAD_MAP.get(emotion_data.primary, VAD_MAP["neutral"])
```
And change return to:
```python
return {"emotion": emotion_data.primary, "emotion_vad": vad.to_tuple()}
```

**Step 3: Verify import**

Run: `PYTHONPATH=src python -c "from animetta.orchestration.graph.emotion_node import emotion_node; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add src/animetta/orchestration/graph/emotion_node.py
git commit -m "feat(emotion_node): add VAD vector output for V2 memory"
```

---

### Task 1.3: Update output_node — replace MemoryTurn with encode()

**Files:**
- Modify: `src/animetta/orchestration/graph/output_node.py`

**Step 1: Read current _store_conversation_to_memory method**

**Step 2: Replace the method**

Remove the `from ...memory.models.turns import MemoryTurn` import (the only hard import from memory/ in the entire codebase).

Replace `_store_conversation_to_memory()` body:
```python
async def _store_conversation_to_memory(state, config):
    memory_system = _get_memory_system(config)
    if not memory_system:
        return

    user_text = state.get("user_text", "")
    response_text = state.get("response_text", "")
    session_id = state.get("session_id", "unknown")
    vad_tuple = state.get("emotion_vad")

    from animetta.memory.v2.emotion_field import VADVector
    vad = VADVector(*vad_tuple) if vad_tuple else None

    try:
        await memory_system.encode(
            user_input=user_text,
            agent_response=response_text,
            emotion_vad=vad,
            session_id=session_id,
        )
    except Exception as e:
        logger.warning(f"Memory encoding failed (non-fatal): {e}")
```

Replace `_get_memory_system()`:
```python
def _get_memory_system(config):
    service_context = _get_from_config(config, "service_context")
    if service_context and hasattr(service_context, "memory_system"):
        return service_context.memory_system
    return None
```

**Step 3: Verify import**

Run: `PYTHONPATH=src python -c "from animetta.orchestration.graph.output_node import output_node; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add src/animetta/orchestration/graph/output_node.py
git commit -m "feat(output_node): replace MemoryTurn store with V2 encode()"
```

---

### Task 1.4: Update memory_middleware — unified recall()

**Files:**
- Modify: `src/animetta/orchestration/graph/memory_middleware.py`

**Step 1: Read current before_llm_call method**

**Step 2: Replace with unified recall()**

Replace `before_llm_call()`:
```python
async def before_llm_call(self, session_id: str, user_input: str,
                          current_emotion: Any = None) -> tuple[str, dict]:
    if not self._memory_system:
        return "", {}

    try:
        result = await self._memory_system.recall(
            query=user_input,
            session_id=session_id,
            current_emotion=current_emotion,
        )
    except Exception as e:
        logger.warning(f"Memory recall failed (non-fatal): {e}")
        return "", {}

    # Build injection block from result
    parts = []
    metadata = {}

    if result.atoms:
        summaries = [a.summary or a.content for a in result.atoms[:5]]
        parts.append("## 相关记忆\n" + "\n".join(f"- {s}" for s in summaries))

    if result.profile:
        profile_text = "\n".join(f"- {k}: {v}" for k, v in result.profile.items())
        parts.append(f"## 用户画像\n{profile_text}")

    if result.memes:
        meme_text = "\n".join(f"- {m.summary or m.content}" for m in result.memes[:3])
        parts.append(f"## 活跃梗\n{meme_text}")

    injection = "\n\n".join(parts)
    return injection, metadata
```

Make `after_llm_call()` a no-op (encoding happens in output_node now):
```python
async def after_llm_call(self, *args, **kwargs):
    pass
```

**Step 3: Verify import**

Run: `PYTHONPATH=src python -c "from animetta.orchestration.graph.memory_middleware import MemoryMiddleware; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add src/animetta/orchestration/graph/memory_middleware.py
git commit -m "feat(memory_middleware): unified recall() replacing FuzzyLayer+Profile+Meme"
```

---

### Task 1.5: Update llm_node — adapt retrieval interface

**Files:**
- Modify: `src/animetta/orchestration/graph/llm_node.py`

**Step 1: Find _retrieve_memory_context function**

**Step 2: Update to pass current emotion**

Find where `middleware.before_llm_call()` is called. Update to pass VAD:
```python
from animetta.memory.v2.emotion_field import VADVector

vad_tuple = state.get("emotion_vad")
current_emotion = VADVector(*vad_tuple) if vad_tuple else None

enriched, metadata = await middleware.before_llm_call(
    session_id=session_id,
    user_input=query,
    current_emotion=current_emotion,
)
```

Remove `injection_tier` parameter — no longer needed.

**Step 3: Verify import**

Run: `PYTHONPATH=src python -c "from animetta.orchestration.graph.llm_node import llm_node; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add src/animetta/orchestration/graph/llm_node.py
git commit -m "feat(llm_node): pass VAD emotion to memory recall"
```

---

### Task 1.6: Update service_context — init LivingMemorySystem

**Files:**
- Modify: `src/animetta/core/service_context.py`

**Step 1: Replace init_memory method**

```python
async def init_memory(self):
    """Initialize LivingMemorySystem V2."""
    from animetta.memory.v2.system import LivingMemorySystem
    self.memory_system = LivingMemorySystem(
        db_path="memory_db/living_memory.sqlite"
    )
    await self.memory_system.initialize()
    logger.info(f"[{self.session_id}] LivingMemory V2 initialized")
```

**Step 2: Update close method memory cleanup**

```python
if self.memory_system:
    await self.memory_system.shutdown()
```

**Step 3: Verify import**

Run: `PYTHONPATH=src python -c "from animetta.core.service_context import ServiceContext; print('OK')"`
Expected: OK

**Step 4: Commit**

```bash
git add src/animetta/core/service_context.py
git commit -m "feat(service_context): init LivingMemorySystem V2, fix MemorySystem NameError"
```

---

## Phase 2: Legacy Memory Cleanup

### Task 2.1: Create _legacy directory and move old modules

**Files:**
- Create: `src/animetta/memory/_legacy/__init__.py`
- Move: 30+ files into `_legacy/`

**Step 1: Create _legacy/ and move files**

```bash
mkdir -p src/animetta/memory/_legacy
git mv src/animetta/memory/system.py src/animetta/memory/_legacy/
git mv src/animetta/memory/manager.py src/animetta/memory/_legacy/
git mv src/animetta/memory/fuzzy_layer.py src/animetta/memory/_legacy/
git mv src/animetta/memory/fact_extractor.py src/animetta/memory/_legacy/
git mv src/animetta/memory/user_profile.py src/animetta/memory/_legacy/
git mv src/animetta/memory/prompts.py src/animetta/memory/_legacy/
git mv src/animetta/memory/tools.py src/animetta/memory/_legacy/
git mv src/animetta/memory/config.py src/animetta/memory/_legacy/
git mv src/animetta/memory/models/ src/animetta/memory/_legacy/
git mv src/animetta/memory/search/ src/animetta/memory/_legacy/
git mv src/animetta/memory/stores/ src/animetta/memory/_legacy/
git mv src/animetta/memory/meme/ src/animetta/memory/_legacy/
git mv src/animetta/memory/learner/ src/animetta/memory/_legacy/
git mv src/animetta/memory/fuzzy/ src/animetta/memory/_legacy/
```

**Step 2: Write _legacy/__init__.py**

```python
"""DEPRECATED — Legacy memory modules. Use animetta.memory.v2 instead."""
```

**Step 3: Commit**

```bash
git add src/animetta/memory/_legacy/
git commit -m "refactor(memory): move legacy modules to _legacy/"
```

---

### Task 2.2: Remove orchestrator legacy logic

**Files:**
- Modify: `src/animetta/orchestration/graph/orchestrator.py`

**Step 1: Remove _query_depth_map and related code**

Delete:
- `self._query_depth_map: Dict[str, Dict[str, Any]] = {}`
- `_compute_injection_tier()` method
- Any reference to `injection_tier` in state initialization

**Step 2: Commit**

```bash
git add src/animetta/orchestration/graph/orchestrator.py
git commit -m "refactor(orchestrator): remove _query_depth_map legacy memory concept"
```

---

### Task 2.3: Archive old memory config

**Files:**
- Move: `config/features/memory.yaml` → `config/features/memory.yaml.legacy`

**Step 1: Rename**

```bash
git mv config/features/memory.yaml config/features/memory.yaml.legacy
```

**Step 2: Commit**

```bash
git add config/features/memory.yaml.legacy
git commit -m "refactor(config): archive legacy memory.yaml config"
```

---

## Phase 3: Test Debt Cleanup

### Task 3.1: Create batch-fix script for test $$$ → proper imports

**Files:**
- Create: `scripts/fix_test_imports.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Batch fix `from animetta import $$$` in test files to proper submodule imports."""
import re
import os

# Map of symbol → correct import module
SYMBOL_MAP = {
    # Orchestration graph
    "llm_node": "animetta.orchestration.graph",
    "emotion_node": "animetta.orchestration.graph",
    "output_node": "animetta.orchestration.graph",
    "tool_node": "animetta.orchestration.graph",
    "asr_node": "animetta.orchestration.graph",
    "tts_node": "animetta.orchestration.graph",
    "personality_node": "animetta.orchestration.graph",
    "create_initial_state": "animetta.orchestration.graph.state",
    "AgentState": "animetta.orchestration.graph.state",
    "MemoryMiddleware": "animetta.orchestration.graph.memory_middleware",
    "LangGraphOrchestrator": "animetta.orchestration.graph.orchestrator",
    "ToolManager": "animetta.orchestration.graph.tool_manager",
    # LLM services
    "LLMInterface": "animetta.services.intelligence.llm",
    "LLMFactory": "animetta.services.intelligence.llm",
    "MockLLM": "animetta.services.intelligence.llm",
    "GLMLLM": "animetta.services.intelligence.llm",
    "OpenAILLM": "animetta.services.intelligence.llm",
    "OllamaLLM": "animetta.services.intelligence.llm",
    "LocalLoraLLM": "animetta.services.intelligence.llm",
    # TTS services
    "TTSInterface": "animetta.services.speech.tts",
    "TTSFactory": "animetta.services.speech.tts",
    "MockTTS": "animetta.services.speech.tts",
    "EdgeTTS": "animetta.services.speech.tts",
    # Memory
    "MemorySystem": "animetta.memory._legacy.system",
    "MemoryManager": "animetta.memory._legacy.manager",
    "FuzzyLayer": "animetta.memory._legacy.fuzzy_layer",
    # Tools
    "calculator": "animetta.tools",
    "MCPManager": "animetta.tools",
    "MCPClient": "animetta.tools.mcp_bridge",
    "MinecraftBridge": "animetta.tools.minecraft.bridge",
    "AutonomousLoop": "animetta.tools.minecraft.autonomous",
    # Utils
    "EnvHelper": "animetta.utils.env_helper",
}

# Also fix stale src.anima → animetta
STALE_PATH_FIX = ("src.anima", "animetta")


def fix_file(filepath: str) -> int:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    changes = 0

    # Fix stale src.anima paths
    if STALE_PATH_FIX[0] in content:
        content = content.replace(STALE_PATH_FIX[0], STALE_PATH_FIX[1])
        changes += 1

    # Fix $$$ imports — remove them (they'll be replaced below)
    content = re.sub(r'^\s*from animetta import \$\$\$\s*$', '', content, flags=re.MULTILINE)
    changes += 1

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return changes


def main():
    test_dirs = ['tests/', 'scripts/', 'evaluations/']
    for d in test_dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith('.py'):
                    path = os.path.join(root, f)
                    changes = fix_file(path)
                    if changes:
                        print(f"Fixed {path} ({changes} changes)")


if __name__ == '__main__':
    main()
```

**Step 2: Run the script**

```bash
PYTHONPATH=src python scripts/fix_test_imports.py
```

**Step 3: Verify test collection**

Run: `PYTHONPATH=src python -m pytest tests/ --co -q 2>&1 | tail -5`
Expected: All test files collected without SyntaxError/ImportError

**Step 4: Commit**

```bash
git add scripts/fix_test_imports.py tests/ scripts/ evaluations/
git commit -m "fix(tests): batch fix $$$ placeholders and stale src.anima paths"
```

---

### Task 3.2: Manual fixes for edge cases

**Files:** Various test files that the script can't auto-fix

**Step 1: Run test collection and identify remaining failures**

```bash
PYTHONPATH=src python -m pytest tests/ --co -q 2>&1 | grep "ERROR"
```

**Step 2: Fix any remaining import errors manually**

For each failing file, add proper `from animetta.X import Y` at module level.

**Step 3: Verify all files collect**

```bash
PYTHONPATH=src python -m pytest tests/ --co -q 2>&1 | grep -c "ERROR"
```
Expected: 0 errors

**Step 4: Commit**

```bash
git add tests/
git commit -m "fix(tests): manual fixes for remaining import edge cases"
```

---

## Phase 4: NameError Remediation

### Task 4.1: Fix critical path source files

**Files:**
- `src/animetta/services/intelligence/llm/factory.py`
- `src/animetta/services/intelligence/llm/openai_llm.py`
- `src/animetta/services/intelligence/llm/glm_llm.py`
- `src/animetta/services/speech/tts/factory.py`
- `src/animetta/services/speech/asr/factory.py`

**Step 1: For each file, check for names used but not imported**

```bash
# Example for factory.py
grep -n "LLMConfig\|LLMInterface\|ProviderRegistry" src/animetta/services/intelligence/llm/factory.py
```

**Step 2: Add missing imports at module level**

```python
# factory.py — add
from animetta.config.providers.llm import LLMConfig
from animetta.services.intelligence.llm.interface import LLMInterface
```

**Step 3: Verify import for each file**

```bash
PYTHONPATH=src python -c "from animetta.services.intelligence.llm.factory import LLMFactory; print('OK')"
```

**Step 4: Commit**

```bash
git add src/animetta/services/intelligence/llm/*.py src/animetta/services/speech/tts/*.py src/animetta/services/speech/asr/*.py
git commit -m "fix(services): add missing imports after $$$ removal"
```

---

### Task 4.2: Full package import verification

**Step 1: Smoke test — import all key modules**

```bash
PYTHONPATH=src python -c "
from animetta.memory.v2 import LivingMemorySystem
from animetta.orchestration.graph import llm_node, emotion_node, output_node
from animetta.core.service_context import ServiceContext
print('ALL CRITICAL IMPORTS OK')
"
```

**Step 2: Run V2 tests again to ensure no regression**

```bash
PYTHONPATH=src python -m pytest tests/memory_v2/ -v -p no:xdist -o 'addopts='
```
Expected: 45 passed

**Step 3: Commit final state**

```bash
git add -A
git commit -m "chore: final verification — all critical imports + 45/45 V2 tests passing"
```

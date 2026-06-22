# 记忆模块架构重构 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将三个平行存储 (Wiki / FuzzyMemory / MemePool) 合并为 Wiki 唯一持久层，Fuzzy 变为运行时虚层，去掉前端搜索按钮，自动注入 LLM context。

**Architecture:** Wiki 统一存储 (entities/concepts/synthesis/memes)，FuzzyLayer 纯计算不落盘，MemoryMiddleware 自动三级注入。调度任务统一写 wiki。

**Tech Stack:** Python 3.13, SQLite, Chroma, asyncio, Vue 3, TypeScript, Socket.IO

**Design doc:** `docs/plans/2026-05-10-memory-architecture-refactor-design.md`

---

### Task 1: PageType 加 MEME + Wiki 目录初始化

**Files:**
- Modify: `src/animetta/memory/wiki/models.py`
- Modify: `src/animetta/memory/wiki/manager.py`

**Step 1: PageType 加 MEME**

`models.py` — 在 `PageType` 枚举加一项：

```python
class PageType(Enum):
    ENTITY = "entity"
    CONCEPT = "concept"
    SOURCE = "source"
    SYNTHESIS = "synthesis"
    MEME = "meme"  # ← 新增
```

**Step 2: PAGE_SUBDIRS + 目录初始化 + rebuild_index**

`manager.py` — 三处修改：

```python
# 1. PAGE_SUBDIRS
PAGE_SUBDIRS = {
    PageType.ENTITY: "entities",
    PageType.CONCEPT: "concepts",
    PageType.SOURCE: "sources",
    PageType.SYNTHESIS: "synthesis",
    PageType.MEME: "memes",         # ← 新增
}

# 2. _init_structure() 加 memes/
for d in (..., self._wiki_dir / "memes"):
    d.mkdir(parents=True, exist_ok=True)

# 3. rebuild_index() 加 Memes section
sections = {
    "Entities": ..., "Concepts": ..., "Sources": ..., "Synthesis": ...,
    "Memes": self.list_pages(PageType.MEME),  # ← 新增
}
```

**Step 3: 验证**

Run: `PYTHONPATH=src python -c "from anima.memory.wiki.models import PageType; assert PageType.MEME.value == 'meme'"`
Expected: no error

**Step 4: Commit**

```bash
git add src/animetta/memory/wiki/models.py src/animetta/memory/wiki/manager.py
git commit -m "refactor(memory): add PageType.MEME and wiki/memes/ directory"
```

---

### Task 2: MemeStore 改为 Wiki 适配层

**Files:**
- Rewrite: `src/animetta/memory/meme/store.py`
- Modify: `src/animetta/memory/meme/engine.py`
- Modify: `src/animetta/memory/system.py`

**Step 1: 重写 MemeStore，读写走 wiki**

`store.py` — 保持 `MemeStore` 类名和所有公开方法签名不变，内部实现改为操作 WikiPage：

```python
class MemeStore:
    """Meme CRUD backed by WikiManager (wiki/memes/)."""

    def __init__(self, wiki: WikiManager) -> None:
        self._wiki = wiki

    def insert(self, meme: Meme) -> str:
        page = self._meme_to_page(meme)
        self._wiki.write_page(page)
        return meme.id

    def update(self, meme: Meme) -> None:
        self._wiki.write_page(self._meme_to_page(meme))

    def get(self, meme_id: str) -> Optional[Meme]:
        page = self._wiki.read_page(f"memes/{meme_id}.md")
        return self._page_to_meme(page) if page else None

    def get_active(self, limit: int = 10) -> List[Meme]:
        all_pages = self._wiki.list_pages(PageType.MEME)
        memes = []
        for p in all_pages:
            page = self._wiki.read_page(p)
            m = self._page_to_meme(page) if page else None
            if m and m.is_active:
                memes.append(m)
        memes.sort(key=lambda m: m.current_score, reverse=True)
        return memes[:limit]

    def get_inactive(self, limit: int = 50) -> List[Meme]:
        ... # 同上, filter not is_active

    def list_active(self) -> List[Meme]:
        return self.get_active(limit=9999)

    def list_discarded(self) -> List[Meme]:
        return self.get_inactive(limit=9999)

    def save(self, meme: Meme) -> str:
        return self.insert(meme)

    def discard(self, meme_id: str) -> None:
        self.set_active(meme_id, False)

    def resurrect(self, meme_id: str) -> None:
        self.set_active(meme_id, True)

    def set_active(self, meme_id: str, active: bool) -> None:
        page = self._wiki.read_page(f"memes/{meme_id}.md")
        if page:
            page.metadata["is_active"] = active
            self._wiki.write_page(page)

    def update_score(self, meme_id: str, new_score: float) -> None:
        page = self._wiki.read_page(f"memes/{meme_id}.md")
        if page:
            page.metadata["current_score"] = new_score
            self._wiki.write_page(page)

    def increment_use(self, meme_id: str) -> None:
        page = self._wiki.read_page(f"memes/{meme_id}.md")
        if page:
            page.metadata["use_count"] = page.metadata.get("use_count", 0) + 1
            page.metadata["last_used_at"] = datetime.now().isoformat()
            self._wiki.write_page(page)

    def delete(self, meme_id: str) -> None:
        path = self._wiki._wiki_dir / "memes" / f"{meme_id}.md"
        if path.exists():
            path.unlink()

    def count_active(self) -> int:
        return len(self.get_active(limit=9999))

    def close(self) -> None:
        pass

    # ── conversion helpers ──
    def _meme_to_page(self, meme: Meme) -> WikiPage:
        return WikiPage(
            title=meme.text[:50], page_type=PageType.MEME,
            path=f"memes/{meme.id}.md", content=meme.text,
            tags=meme.tags.copy(),
            metadata={
                "id": meme.id, "context_hint": meme.context_hint,
                "source": meme.source.value,
                "base_score": meme.base_score,
                "current_score": meme.current_score,
                "use_count": meme.use_count,
                "last_used_at": meme.last_used_at.isoformat() if meme.last_used_at else None,
                "is_active": meme.is_active,
                "resurrection_count": meme.resurrection_count,
            },
        )

    def _page_to_meme(self, page: WikiPage) -> Optional[Meme]:
        md = page.metadata
        if not md.get("id"):
            return None
        return Meme(
            id=md["id"], text=page.content,
            context_hint=md.get("context_hint", ""),
            source=MemeSource(md.get("source", "ai")),
            tags=page.tags,
            base_score=md.get("base_score", 0.7),
            current_score=md.get("current_score", 0.7),
            use_count=md.get("use_count", 0),
            last_used_at=datetime.fromisoformat(md["last_used_at"]) if md.get("last_used_at") else None,
            is_active=md.get("is_active", True),
            resurrection_count=md.get("resurrection_count", 0),
        )
```

**Step 2: MemePool 构造改为接收 WikiManager**

`engine.py`：

```python
class MemePool:
    def __init__(self, wiki: WikiManager, config: Optional[Dict[str, Any]] = None) -> None:
        from .store import MemeStore
        self.store = MemeStore(wiki)
        ...
```

更新 import：去掉 `from .store import MemeStore` 改为 `from ..wiki.manager import WikiManager`

**Step 3: 改 system.py 初始化**

`system.py` — 创建 MemePool 时传 wiki_manager：

```python
from pathlib import Path as _Path
meme_config = config.get("meme_pool", {})
if meme_config.get("enabled", True):
    try:
        if not self._wiki_manager:
            logger.warning("[MemorySystem] WikiManager unavailable, MemePool disabled")
        else:
            self.meme_pool = MemePool(
                wiki=self._wiki_manager,
                config=meme_config,
            )
            logger.info("[MemorySystem] MemePool initialized (wiki-backed)")
    except Exception as e:
        logger.warning(f"[MemorySystem] MemePool init failed: {e}")
```

删除旧的 meme_db 相关代码。

**Step 4: 验证**

Run: `PYTHONPATH=src python -m pytest tests/test_memory_evolution.py -v --tb=short -k "MemePool"`
Expected: 12 passed

**Step 5: Commit**

```bash
git add src/animetta/memory/meme/ src/animetta/memory/system.py
git commit -m "refactor(memory): MemeStore backed by WikiManager"
```

---

### Task 3: 迁移现有 FuzzyMemory 到 wiki synthesis/

**Files:**
- Create: `scripts/migrate_fuzzy_to_wiki.py`
- No production code changes

**Step 1: 写迁移脚本**

```python
#!/usr/bin/env python3
"""One-time migration: read FuzzyMemoryStore → wiki/synthesis/fuzzy-<id>.md"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

async def migrate():
    from anima.memory.fuzzy.store import FuzzyMemoryStore
    from anima.memory.wiki.manager import WikiManager
    from anima.memory.wiki.models import WikiPage, PageType
    from anima.memory.manager import MemoryManager
    from anima.memory.config import MemoryConfig

    ws = Path("~/.anima/workspace").expanduser()
    fuzzy = FuzzyMemoryStore(str(ws / "fuzzy_memory.sqlite"))
    fuzzy.open()
    mgr = MemoryManager(config=MemoryConfig(workspace_dir=str(ws)))
    wiki = WikiManager(mgr)

    count = 0
    for m in fuzzy.search_fuzzy(limit=9999):
        path = f"synthesis/fuzzy-{m.id}.md"
        if wiki.page_exists(path):
            continue
        wiki.write_page(WikiPage(
            title=f"模糊记忆: {m.text[:40]}",
            page_type=PageType.SYNTHESIS,
            path=path, content=m.text,
            tags=[m.granularity.value, "migrated-fuzzy"],
            metadata={"confidence": m.confidence, "session_id": m.session_id},
        ))
        count += 1

    fuzzy.close()
    print(f"Migrated {count} fuzzy memories to wiki/synthesis/")

if __name__ == "__main__":
    import asyncio
    asyncio.run(migrate())
```

**Step 2: 运行**

Run: `PYTHONPATH=src python scripts/migrate_fuzzy_to_wiki.py`

**Step 3: Commit**

```bash
git add scripts/migrate_fuzzy_to_wiki.py
git commit -m "feat: migrate FuzzyMemory → wiki synthesis pages"
```

---

### Task 4: 实现 FuzzyLayer 虚层

**Files:**
- Create: `src/animetta/memory/fuzzy_layer.py`
- Modify: `src/animetta/memory/__init__.py`

**Step 1: 创建 FuzzyLayer**

`fuzzy_layer.py`：

```python
"""FuzzyLayer — runtime fuzzification, no persistent storage."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .wiki.manager import WikiManager
from .stores.short_term import ShortTermMemory
from .models.turns import MemoryTurn

logger = logging.getLogger(__name__)


class FuzzyLayer:
    """Runtime fuzzification layer.

    On each LLM call, synthesizes 'I remember...' narratives
    from wiki + short-term memory. No independent storage.
    """

    def __init__(
        self,
        wiki: Optional[WikiManager] = None,
        short_term: Optional[ShortTermMemory] = None,
    ):
        self._wiki = wiki
        self._short_term = short_term
        self._cache: Dict[str, Tuple[str, float]] = {}

    async def build_fuzzy_context(
        self, session_id: str, query: str, max_synthesis: int = 3
    ) -> str:
        """Build fuzzy narrative context for LLM injection."""
        parts: List[str] = []

        turns = self._get_recent_turns(session_id, 5)
        if turns:
            lines = ["## 最近对话"]
            for t in turns:
                lines.append(f"- 用户: {t.user_input[:100]}")
                if t.agent_response:
                    lines.append(f"  回应: {t.agent_response[:100]}")
            parts.append("\n".join(lines))

        synthesis = self._get_relevant_synthesis(query, max_synthesis)
        if synthesis:
            parts.append("## 我记得的\n" + "\n".join(f"- {s}" for s in synthesis))

        profile = self._get_profile_text(session_id)
        if profile:
            parts.append(f"## 用户画像\n{profile}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def _get_recent_turns(self, session_id: str, n: int) -> List[MemoryTurn]:
        return self._short_term.get_recent(session_id, n) if self._short_term else []

    def _get_relevant_synthesis(self, query: str, max_items: int) -> List[str]:
        if not self._wiki:
            return []
        now = datetime.now().timestamp()
        # Check cache first
        cached = []
        for path, (text, ts) in list(self._cache.items()):
            if now - ts > 300:
                del self._cache[path]
                continue
            if any(w in text for w in query.lower().split()):
                cached.append(text)
        if cached:
            return cached[:max_items]

        from .wiki.models import PageType
        results = []
        for rel in self._wiki.list_pages(PageType.SYNTHESIS)[-max_items:]:
            page = self._wiki.read_page(rel)
            if page:
                text = page.content[:200]
                self._cache[rel] = (text, now)
                results.append(text)
        return results[:max_items]

    def _get_profile_text(self, session_id: str) -> str:
        if not self._wiki:
            return ""
        parts = []
        for rel in self._wiki.list_pages():
            if rel.startswith("entities/"):
                page = self._wiki.read_page(rel)
                if page and page.content:
                    parts.append(f"- {page.content[:150]}")
        return "\n".join(parts)

    def invalidate_cache(self, path: Optional[str] = None) -> None:
        if path:
            self._cache.pop(path, None)
        else:
            self._cache.clear()
```

**Step 2: 更新 `__init__.py`**

```python
from .fuzzy_layer import FuzzyLayer
```

**Step 3: 验证**

Run: `PYTHONPATH=src python -c "from anima.memory.fuzzy_layer import FuzzyLayer; print('OK')"`

**Step 4: Commit**

```bash
git add src/animetta/memory/fuzzy_layer.py src/animetta/memory/__init__.py
git commit -m "refactor(memory): add FuzzyLayer — runtime fuzzification without storage"
```

---

### Task 5: MemoryMiddleware 改用 FuzzyLayer

**Files:**
- Modify: `src/animetta/orchestration/graph/memory_middleware.py`
- Modify: `src/animetta/memory/system.py`

**Step 1: system.py 初始化 FuzzyLayer**

`system.py` 中 FuzzyMemoryStore/FuzzyConsolidator 初始化的位置改为 FuzzyLayer：

```python
# FuzzyLayer (replaces FuzzyMemoryStore + FuzzyConsolidator)
self.fuzzy_layer: Optional[FuzzyLayer] = None
if self._wiki_manager:
    try:
        self.fuzzy_layer = FuzzyLayer(
            wiki=self._wiki_manager,
            short_term=self._short_term,
        )
        logger.info("[MemorySystem] FuzzyLayer initialized")
    except Exception as e:
        logger.warning(f"[MemorySystem] FuzzyLayer init failed: {e}")
```

删除旧的 fuzzy memory 初始化代码（fuzzy_config, FuzzyMemoryStore, FuzzyConsolidator）。

**Step 2: MemoryMiddleware 注入源改为 FuzzyLayer**

`memory_middleware.py` — `before_llm_call` 简化：

```python
async def before_llm_call(
    self, session_id, user_input, base_prompt=None, injection_tier=1,
):
    if not self._memory_system:
        return base_prompt or "", None

    metadata: Dict[str, Any] = {"tier": injection_tier}
    injection_parts: List[str] = []

    # Use FuzzyLayer instead of old retrieve_context + MemoryLayer
    fuzzy_layer = getattr(self._memory_system, "fuzzy_layer", None)
    if fuzzy_layer:
        try:
            ctx = await fuzzy_layer.build_fuzzy_context(
                session_id=session_id, query=user_input,
            )
            if ctx:
                injection_parts.append(ctx)
                metadata["mode"] = "fuzzy_layer"
        except Exception as e:
            logger.warning(f"[MemoryMiddleware] FuzzyLayer failed: {e}")

    # User profile
    try:
        profile = self._memory_system.get_profile(session_id)
        if profile and not profile.is_empty():
            pt = profile.format_for_prompt()
            if pt:
                injection_parts.append(pt)
    except Exception as e:
        logger.warning(f"[MemoryMiddleware] profile failed: {e}")

    if not injection_parts:
        return base_prompt or "", metadata

    enriched = self._inject_into_prompt(
        base_prompt or "",
        "\n\n---\n\n".join(injection_parts),
        injection_tier,
    )
    return enriched, metadata
```

删除 `_format_memory_turns` 和 `MemoryLayer` 相关代码。

**Step 3: 验证**

Run: `PYTHONPATH=src python -c "from anima.orchestration.graph.memory_middleware import MemoryMiddleware; print('OK')"`

**Step 4: Commit**

```bash
git add src/animetta/memory/system.py src/animetta/orchestration/graph/memory_middleware.py
git commit -m "refactor(memory): MemoryMiddleware uses FuzzyLayer, remove old MemoryLayer path"
```

---

### Task 6: 去掉前端搜索 + 改记忆面板为 wiki 浏览

**Files:**
- Rewrite: `frontend/src/stores/memory.ts`
- Modify: `frontend/src/components/memory/MemoryPanel.vue`
- Modify: `frontend/src/composables/useChat.ts`
- Modify: `src/animetta/orchestration/server/routes.py`

**Step 1: 后端加 get_wiki_pages 事件，删旧 fuzzy 事件**

`routes.py`：

```python
# 新增 handler
async def on_get_wiki_pages(self, sid: str, data: dict) -> dict:
    try:
        ctx = self.session_manager.get_context(sid)
        if not ctx or not ctx.memory_system:
            return {'pages': []}
        wiki = getattr(ctx.memory_system, '_wiki_manager', None)
        if not wiki:
            return {'pages': []}
        pages = []
        for rel in wiki.list_pages():
            page = wiki.read_page(rel)
            if page:
                pages.append({
                    'path': page.path,
                    'title': page.title,
                    'page_type': page.page_type.value,
                    'content': page.content[:200],
                    'tags': page.tags,
                    'updated_at': page.updated_at.isoformat() if page.updated_at else '',
                })
        return {'pages': pages}
    except Exception as e:
        logger.error(f"[{sid}] get_wiki_pages failed: {e}")
        return {'pages': []}

# 注册路由 (替换旧 fuzzy 事件)
sio.on('get_wiki_pages', handlers.on_get_wiki_pages)
# 删除: sio.on('get_fuzzy_memories', ...)
# 删除: sio.on('get_fuzzy_memory_sources', ...)

# 删除 handler 方法:
# on_get_fuzzy_memories
# on_get_fuzzy_memory_sources
```

**Step 2: 前端 store 改为 wiki 浏览**

`memory.ts` — 从 FuzzyMemory 接口改为 WikiPageEntry：

```typescript
export interface WikiPageEntry {
  path: string
  title: string
  page_type: string
  content: string
  tags: string[]
  updated_at: string
}

// fetchMemories → fetchWikiPages
async function fetchWikiPages(sessionId: string): Promise<void> {
  const socket = getSocket()
  if (!socket) return
  loading.value = true
  socket.emit('get_wiki_pages', { session_id: sessionId },
    (response: { pages: WikiPageEntry[] }) => {
      wikiPages.value = response.pages ?? []
      loading.value = false
    })
}
```

**Step 3: MemoryPanel.vue 改为 wiki 页面列表**

- 筛选按钮改为 page_type: 全部 / entity / concept / synthesis / meme
- 列表显示标题 + 类型标签 + 更新时间
- 加载文字改为"加载 wiki 页面..."

**Step 4: useChat.ts organizeMemory 刷新改为 get_wiki_pages**

```typescript
socket.on('memory.organize.result', () => {
  store.memoryOrganizing = false
  socket.emit('get_wiki_pages', { session_id: 'default' })
})
```

**Step 5: 验证**

Run: `cd frontend && npx vue-tsc --noEmit --skipLibCheck`
Expected: no output

**Step 6: Commit**

```bash
git add frontend/src/ src/animetta/orchestration/server/routes.py
git commit -m "refactor: replace fuzzy memory search with wiki page browsing"
```

---

### Task 7: 清理废弃代码 + 删除旧 SQLite 表

**Files:**
- Remove: `src/animetta/memory/fuzzy/store.py`
- Remove: `src/animetta/memory/fuzzy/consolidator.py`
- Remove: `src/animetta/orchestration/graph/meme_inject_node.py`
- Remove: `src/animetta/orchestration/graph/memory_layer.py` (deprecated, logic in FuzzyLayer)
- Modify: `src/animetta/memory/fuzzy/__init__.py`
- Modify: `src/animetta/orchestration/graph/__init__.py` (if meme_inject_node exported)

**Step 1: git rm 废弃文件**

```bash
git rm src/animetta/memory/fuzzy/store.py
git rm src/animetta/memory/fuzzy/consolidator.py
git rm src/animetta/orchestration/graph/meme_inject_node.py
git rm src/animetta/orchestration/graph/memory_layer.py
```

**Step 2: 更新 `fuzzy/__init__.py`**

移除已删除模块的导入。

**Step 3: 全局检查引用**

```bash
grep -rn "FuzzyMemoryStore\|FuzzyConsolidator\|meme_inject_node\|from.*memory_layer" src/ tests/ --include="*.py"
```

修复所有残留引用。

**Step 4: 验证**

Run: `PYTHONPATH=src python -m pytest tests/ -v --tb=short`
Expected: all pass

**Step 5: Commit**

```bash
git add -A
git commit -m "cleanup: remove deprecated FuzzyMemoryStore, memory_layer, meme_inject_node"
```

---

### Task 8: 调度任务改为写 wiki

**Files:**
- Modify: `src/animetta/memory/learner/engine.py`

**Step 1: 简化 engine.py — 去掉 SQLite 存储方法**

删除：`_ensure_db()`, `_store_logs()`, `_get_recent_logs()`, `_row_to_learninglog()`, `_load_processed_sessions()`, `_upsert_processed_session()`

**Step 2: consolidate_conversations 改为写 wiki sources/**

```python
async def consolidate_conversations(self) -> None:
    ...
    logs = await self._summarizer.summarize_batch(sessions)
    wiki = self._memory_system._wiki_manager
    for log in logs:
        date_key = log.created_at.strftime("%Y-%m-%d") if log.created_at else datetime.now().strftime("%Y-%m-%d")
        page = WikiPage(
            title=f"对话摘要 {date_key}",
            page_type=PageType.SOURCE,
            path=f"sources/{date_key}.md",
            content=log.content,
            tags=["daily", date_key],
        )
        wiki.write_page(page)
```

**Step 3: extract_patterns 改为写 wiki concepts/**

```python
async def extract_patterns(self) -> None:
    ...
    for pattern in all_patterns:
        wiki.write_page(WikiPage(
            title=f"模式: {pattern.content[:40]}",
            page_type=PageType.CONCEPT,
            path=f"concepts/pattern-{pattern.id}.md",
            content=pattern.content,
            tags=["pattern", "extracted"],
        ))
```

**Step 4: maintain_meme_pool 保持现状** — 已经走 wiki（Task 2 做完）

**Step 5: prune_logs 改为清理 wiki 过期页面**

```python
async def prune_logs(self) -> None:
    """Clean up wiki sources/ pages older than retention."""
    cutoff = datetime.now().timestamp() - (self._log_retention_days * 86400)
    wiki = self._memory_system._wiki_manager
    for rel in wiki.list_pages(PageType.SOURCE):
        page = wiki.read_page(rel)
        if page and page.updated_at and page.updated_at.timestamp() < cutoff:
            path = wiki._wiki_dir / page.path
            if path.exists():
                path.unlink()
                logger.info(f"Pruned old wiki page: {page.path}")
```

**Step 6: 验证**

Run: `PYTHONPATH=src python -c "from anima.memory.learner.engine import PeriodicLearner; print('OK')"`

**Step 7: Commit**

```bash
git add src/animetta/memory/learner/engine.py
git commit -m "refactor(learner): PeriodicLearner writes to wiki instead of SQLite"
```

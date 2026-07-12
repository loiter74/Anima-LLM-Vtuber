<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMemoryStore } from '@/stores/memory'
import { getSocket } from '@/composables/useSocket'
import type { WikiPageEntry } from '@/stores/memory'
import type { MemoryNode } from '@/types/memoryGraph'
import { Events } from '@/constants/socket-events'
import { sendCanonicalChatText } from '@/composables/chatTransport'
import { useChatStore } from '@/stores/chat'
import MemoryGraph from './MemoryGraph.vue'

const store = useMemoryStore()
const chatStore = useChatStore()

const collapsed = ref(false)
const memeText = ref('')
const correctionDraft = ref('')

// ── View mode (list / graph) ─────────────────────────────────────────
const viewMode = ref<'list' | 'graph'>('list')
const graphInitialized = ref(false)

// ── Graph data ───────────────────────────────────────────────────────
const graphPages = computed<WikiPageEntry[]>(() => {
  // store.wikiPages is the full unfiltered list; store.filteredPages applies search+filter
  return store.filteredPages
})

// ── Node detail panel ────────────────────────────────────────────────
const selectedNode = ref<MemoryNode | null>(null)

function handleNodeClick(node: MemoryNode): void {
  selectedNode.value = node
}

function closeNodeDetail(): void {
  selectedNode.value = null
}

function sendToChat(node: MemoryNode): void {
  const socket = getSocket()
  if (!socket) return
  const command = sendCanonicalChatText(socket, node.content)
  chatStore.createMessage('user', node.content, 'text', command)
  chatStore.isTyping = true
}

function switchView(mode: 'list' | 'graph'): void {
  viewMode.value = mode
  if (mode === 'graph' && !graphInitialized.value) {
    graphInitialized.value = true
  }
  // Clear node detail when switching away from graph
  if (mode === 'list') {
    selectedNode.value = null
  }
}

function addMeme(): void {
  const text = memeText.value.trim()
  if (!text) return
  const socket = getSocket()
  if (!socket) return
  socket.emit(Events.MEME.ADD, { text, source: 'user' }, () => {
    memeText.value = ''
    void refreshMemories()
  })
}

const typeOptions: { key: string | null; label: string }[] = [
  { key: null, label: '全部' },
  { key: 'entity', label: '实体' },
  { key: 'concept', label: '概念' },
  { key: 'synthesis', label: '合成' },
  { key: 'source', label: '来源' },
  { key: 'meme', label: '梗' },
]

const scopeOptions: { key: string | null; label: string }[] = [
  { key: null, label: '全部域' },
  { key: 'character', label: '角色' },
  { key: 'community', label: '社群' },
  { key: 'viewer', label: '观众' },
  { key: 'stream', label: '本场' },
  { key: 'world', label: '世界' },
]

async function refreshMemories(): Promise<void> {
  try {
    await store.fetchMemories({ scope: store.filterScope })
  } catch {
    // The store exposes the structured error state in the panel.
  }
}

async function loadMore(): Promise<void> {
  if (!store.nextCursor) return
  try {
    await store.fetchMemories({
      cursor: store.nextCursor,
      scope: store.filterScope,
      append: true,
    })
  } catch {
    // Structured store error is rendered below.
  }
}

async function togglePin(page: WikiPageEntry): Promise<void> {
  try {
    await store.pinMemory(page.id, page.retention_policy !== 'pinned')
  } catch {
    // Structured store error is rendered below.
  }
}

async function forget(page: WikiPageEntry): Promise<void> {
  try {
    await store.forgetMemory(page.id)
  } catch {
    // Structured store error is rendered below.
  }
}

async function correct(page: WikiPageEntry): Promise<void> {
  const summary = correctionDraft.value.trim()
  if (!summary) return
  try {
    await store.changeMemory(page.id, summary)
    correctionDraft.value = ''
  } catch {
    // Structured store error is rendered below.
  }
}

function formatTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return iso
  }
}

onMounted(() => {
  void refreshMemories()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center px-5 py-4 border-b border-c-border/40 shrink-0">
      <span class="text-xs font-medium flex items-center gap-1.5 flex-1">
        <span>📖</span>
        <span>记忆浏览</span>
      </span>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg
               bg-c-bg/40 text-c-text-dim hover:text-c-text hover:bg-c-bg/60 transition-colors"
        @click="collapsed = !collapsed"
      >
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          :class="collapsed ? 'rotate-180' : ''"
          class="transition-transform"
        >
          <path d="M5 15l7-7 7 7" />
        </svg>
      </button>
    </div>

    <template v-if="!collapsed">
      <!-- View mode tabs -->
      <div class="flex border-b border-c-border/20 shrink-0">
        <button
          class="flex-1 py-2 text-10px font-medium transition-colors"
          :class="viewMode === 'list'
            ? 'text-c-accent border-b-2 border-c-accent'
            : 'text-c-text-dim hover:text-c-text'"
          @click="switchView('list')"
        >
          📋 列表
        </button>
        <button
          class="flex-1 py-2 text-10px font-medium transition-colors"
          :class="viewMode === 'graph'
            ? 'text-c-accent border-b-2 border-c-accent'
            : 'text-c-text-dim hover:text-c-text'"
          @click="switchView('graph')"
        >
          🗺 图谱
        </button>
      </div>

      <!-- Runtime state -->
      <div class="flex items-center gap-2 px-4 py-2 border-b border-c-border/20 text-9px shrink-0">
        <span
          class="px-2 py-1 rounded-full border"
          :class="store.error
            ? 'text-c-error border-c-error/30 bg-c-error/10'
            : store.invalidated
              ? 'text-c-warning border-c-warning/30 bg-c-warning/10'
              : 'text-c-success border-c-success/30 bg-c-success/10'"
        >
          {{ store.error ? store.error.code : store.invalidated ? '有新记忆' : '已同步' }}
        </span>
        <span class="font-mono text-c-text-muted">REV {{ store.revision }}</span>
        <span v-if="store.health.degraded" class="text-c-warning">
          索引降级 · {{ store.health.indexBacklog }} 待处理
        </span>
        <span v-if="store.job" class="text-c-text-dim truncate">
          {{ store.job.status }} · {{ store.job.progress }}%
        </span>
        <div class="flex-1" />
        <button class="px-2 py-1 rounded-lg text-c-accent hover:bg-c-accent/10 duration-200" @click="refreshMemories">
          刷新
        </button>
      </div>

      <!-- Filter bar -->
      <div class="px-4 pt-3 pb-2 border-b border-c-border/20 space-y-2 shrink-0">
        <div class="flex gap-1 flex-wrap">
          <button
            v-for="opt in typeOptions"
            :key="opt.label"
            class="px-2 py-1 rounded-lg text-10px font-medium transition-all"
            :class="store.filterType === opt.key
              ? 'bg-c-accent/20 text-c-accent'
              : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
            @click="store.setFilter(opt.key)"
          >
            {{ opt.label }}
          </button>
        </div>
        <div class="flex gap-1 flex-wrap">
          <button
            v-for="opt in scopeOptions"
            :key="opt.label"
            class="px-2 py-1 rounded-lg text-9px font-medium transition-all duration-200"
            :class="store.filterScope === opt.key
              ? 'bg-c-blue/20 text-c-blue'
              : 'bg-c-bg/40 text-c-text-muted hover:text-c-text'"
            @click="store.setScope(opt.key); refreshMemories()"
          >
            {{ opt.label }}
          </button>
        </div>
        <div class="relative">
          <input
            v-model="store.searchQuery"
            type="text"
            placeholder="搜索页面..."
            class="w-full pl-7 pr-2 py-1 rounded-lg bg-c-bg/60 border border-c-border/30 text-10px text-c-text
                   placeholder:text-c-text-muted focus:outline-none focus:border-c-accent/50 transition-colors"
          />
          <svg
            class="absolute left-2 top-1/2 -translate-y-1/2 text-c-text-muted"
            width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
        </div>
      </div>

      <!-- Page list (list view) -->
      <template v-if="viewMode === 'list'">
        <div class="flex-1 overflow-y-auto px-5 py-4 space-y-2">
          <!-- Loading -->
          <div v-if="store.loading" class="flex items-center justify-center py-8">
            <span class="text-xs text-c-text-dim animate-pulse">加载 wiki 页面...</span>
          </div>

          <!-- Empty -->
          <div v-else-if="store.filteredPages.length === 0" class="flex flex-col items-center justify-center py-10 gap-2">
            <span class="text-lg opacity-40">📖</span>
            <span class="text-10px text-c-text-muted">
              {{ store.searchQuery || store.filterType ? '没有匹配的页面' : '暂无 wiki 页面' }}
            </span>
          </div>

          <!-- Items -->
          <div
            v-for="page in store.filteredPages"
            :key="page.path"
            class="group rounded-xl px-2.5 py-2 cursor-pointer transition-all"
            :class="store.selectedPath === page.path
              ? 'bg-c-accent/10 border border-c-accent/20'
              : 'bg-c-card/30 hover:bg-c-card/60 border border-transparent'"
            @click="store.selectPath(page.path)"
          >
            <div class="flex items-start gap-2">
              <div class="flex-1 min-w-0">
                <p class="text-10px text-c-text font-medium leading-relaxed line-clamp-2 break-words">{{ page.title }}</p>
                <div class="flex items-center gap-2 mt-1">
                  <span class="text-9px px-1.5 py-0.5 rounded font-medium bg-c-bg/60 text-c-text-dim">
                    {{ page.page_type }}
                  </span>
                  <span class="text-9px text-c-text-muted">{{ formatTime(page.updated_at) }}</span>
                  <span class="text-9px text-c-blue">{{ page.scope }}</span>
                  <span v-if="page.retention_policy === 'pinned'" class="text-9px text-c-warning">PIN</span>
                </div>
              </div>
            </div>

            <!-- Expanded content -->
            <Transition name="expand">
              <div v-if="store.selectedPath === page.path" class="mt-2 border-t border-c-border/20 pt-2">
                <p class="text-10px text-c-text-dim leading-relaxed whitespace-pre-wrap line-clamp-6">
                  {{ page.content }}
                </p>
                <div class="mt-2 text-9px text-c-text-muted space-y-1">
                  <p>来源 {{ page.origin.channel || 'unknown' }} · 置信 {{ Math.round(page.confidence * 100) }}% · 显著 {{ Math.round(page.salience * 100) }}%</p>
                  <p v-if="page.subject_ids.length">主体 {{ page.subject_ids.join(', ') }}</p>
                </div>
                <div class="flex gap-1 mt-2" @click.stop>
                  <button class="px-2 py-1 rounded-lg bg-c-warning/10 text-c-warning hover:bg-c-warning/20 duration-200" @click="togglePin(page)">
                    {{ page.retention_policy === 'pinned' ? '取消固定' : '固定' }}
                  </button>
                  <button class="px-2 py-1 rounded-lg bg-c-error/10 text-c-error hover:bg-c-error/20 duration-200" @click="forget(page)">
                    忘记
                  </button>
                </div>
                <div class="flex gap-1 mt-2" @click.stop>
                  <input
                    v-model="correctionDraft"
                    class="flex-1 min-w-0 px-2 py-1 rounded-lg bg-c-bg/60 border border-c-border/30 text-9px text-c-text focus:outline-none focus:border-c-accent/50"
                    placeholder="输入更正后的摘要"
                    @keyup.enter="correct(page)"
                  />
                  <button class="px-2 py-1 rounded-lg bg-c-accent/15 text-c-accent hover:bg-c-accent/25 duration-200" @click="correct(page)">
                    更正
                  </button>
                </div>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Quick add meme -->
        <div class="px-4 py-2 border-t border-c-border/20 shrink-0">
          <div class="flex gap-1">
            <input
              v-model="memeText"
              type="text"
              placeholder="添加梗..."
              class="flex-1 px-2 py-1 rounded-lg bg-c-bg/60 border border-c-border/30 text-10px text-c-text
                     placeholder:text-c-text-muted focus:outline-none focus:border-c-accent/50"
              @keyup.enter="addMeme"
            />
            <button
              class="px-2.5 py-1 rounded-lg text-10px bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-colors"
              :disabled="!memeText.trim()"
              @click="addMeme"
            >
              +
            </button>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-4 py-2 border-t border-c-border/20 shrink-0">
          <div class="flex items-center justify-center gap-2 text-9px text-c-text-muted">
            <span>{{ store.filteredPages.length }} / {{ store.total }} 条记忆</span>
            <button v-if="store.nextCursor" class="px-2 py-1 rounded-lg text-c-accent hover:bg-c-accent/10 duration-200" @click="loadMore">
              加载更多
            </button>
          </div>
        </div>
      </template>

      <!-- Graph view -->
      <template v-else>
        <div class="flex-1 relative overflow-hidden">
          <MemoryGraph
            v-if="graphInitialized"
            :pages="graphPages"
            :search-query="store.searchQuery"
            :selected-category="store.filterType"
            @node-click="handleNodeClick"
          />

          <!-- Node detail panel (overlay) -->
          <Transition name="slide-up">
            <div
              v-if="selectedNode"
              class="absolute bottom-0 left-0 right-0 bg-c-surface/95 backdrop-blur-sm border-t border-c-border/30
                     rounded-t-xl px-4 py-3 max-h-[50%] overflow-y-auto z-10"
            >
              <div class="flex items-start justify-between gap-2 mb-2">
                <h3 class="text-xs font-semibold text-c-text leading-tight flex-1 min-w-0 break-words">
                  {{ selectedNode.label }}
                </h3>
                <button
                  class="w-5 h-5 flex items-center justify-center rounded-md
                         text-c-text-dim hover:text-c-text hover:bg-c-bg/60 transition-colors shrink-0"
                  @click="closeNodeDetail"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div class="flex items-center gap-1.5 mb-2">
                <span class="text-9px px-1.5 py-0.5 rounded font-medium bg-c-accent/15 text-c-accent">
                  {{ selectedNode.category }}
                </span>
                <span class="text-9px px-1.5 py-0.5 rounded font-medium bg-c-bg/60 text-c-text-dim">
                  重要度 {{ Math.round(selectedNode.importance * 100) }}%
                </span>
              </div>
              <p class="text-10px text-c-text-dim leading-relaxed whitespace-pre-wrap">
                {{ selectedNode.content }}
              </p>
              <div class="mt-3 flex justify-end">
                <button
                  class="px-3 py-1 rounded-lg text-10px font-medium
                         bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-colors"
                  @click="sendToChat(selectedNode)"
                >
                  发送到聊天
                </button>
              </div>
            </div>
          </Transition>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }

.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.2s ease-out;
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(100%);
}
</style>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useMemoryStore } from '@/stores/memory'
import { getSocket } from '@/composables/useSocket'
import type { WikiPageEntry } from '@/stores/memory'

const store = useMemoryStore()

const collapsed = ref(false)
const sessionId = ref('default')
const memeText = ref('')

function addMeme(): void {
  const text = memeText.value.trim()
  if (!text) return
  const socket = getSocket()
  if (!socket) return
  socket.emit('meme_add', { text, source: 'user' }, () => {
    memeText.value = ''
    store.fetchWikiPages(sessionId.value)
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
  console.log('[MemoryPanel] mounted, fetching wiki pages...')
  store.fetchWikiPages(sessionId.value)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center px-4 py-3 border-b border-c-border/40 shrink-0">
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

      <!-- Page list -->
      <div class="flex-1 overflow-y-auto px-4 py-3 space-y-2">
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
              </div>
            </div>
          </div>

          <!-- Expanded content -->
          <Transition name="expand">
            <div v-if="store.selectedPath === page.path" class="mt-2 border-t border-c-border/20 pt-2">
              <p class="text-10px text-c-text-dim leading-relaxed whitespace-pre-wrap line-clamp-6">
                {{ page.content }}
              </p>
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
        <p class="text-9px text-c-text-muted text-center">
          {{ store.filteredPages.length }} 个页面
        </p>
      </div>
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
</style>

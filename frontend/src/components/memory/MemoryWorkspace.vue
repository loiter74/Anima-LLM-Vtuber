<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMemoryStore, type WikiPageEntry } from '@/stores/memory'
import type { MemoryNode } from '@/types/memoryGraph'
import MemoryGraph from './MemoryGraph.vue'

const emit = defineEmits<{
  'send-to-sandbox': [content: string]
}>()

const store = useMemoryStore()
const view = ref<'list' | 'graph'>('list')
const selected = ref<WikiPageEntry | null>(null)
const correctionDraft = ref('')
const confirmForgetId = ref('')

const types = [
  { id: '', label: '全部类型' },
  { id: 'entity', label: '实体' },
  { id: 'concept', label: '概念' },
  { id: 'synthesis', label: '合成' },
  { id: 'source', label: '来源' },
  { id: 'meme', label: '梗' },
] as const

const scopes = [
  { id: '', label: '全部作用域' },
  { id: 'character', label: '角色' },
  { id: 'community', label: '社群' },
  { id: 'viewer', label: '观众' },
  { id: 'stream', label: '本场' },
  { id: 'world', label: '世界' },
] as const

const organizing = computed(() => ['accepted', 'running'].includes(store.job?.status ?? ''))

async function refresh(append = false): Promise<void> {
  try {
    await store.fetchMemories({
      scope: store.filterScope,
      cursor: append ? store.nextCursor : null,
      append,
    })
  } catch {
    // The store exposes the structured error below.
  }
}

function selectScope(value: string): void {
  store.setScope(value || null)
  void refresh()
}

function selectType(value: string): void {
  store.setFilter(value || null)
  selected.value = null
}

function selectPage(page: WikiPageEntry): void {
  selected.value = page
  correctionDraft.value = page.summary ?? page.content
  confirmForgetId.value = ''
}

function selectGraphNode(node: MemoryNode): void {
  const page = store.wikiPages.find((item) => item.id === node.id || item.path === node.id)
  if (page) selectPage(page)
}

async function organize(): Promise<void> {
  try {
    await store.organizeMemory()
  } catch {
    // The store exposes the structured error below.
  }
}

async function togglePin(page: WikiPageEntry): Promise<void> {
  try {
    selected.value = await store.pinMemory(page.id, page.retention_policy !== 'pinned')
  } catch {
    // The store exposes the structured error below.
  }
}

async function forget(page: WikiPageEntry): Promise<void> {
  if (confirmForgetId.value !== page.id) {
    confirmForgetId.value = page.id
    return
  }
  try {
    await store.forgetMemory(page.id)
    confirmForgetId.value = ''
    selected.value = null
    await refresh()
  } catch {
    // The store exposes the structured error below.
  }
}

async function saveCorrection(): Promise<void> {
  if (!selected.value || !correctionDraft.value.trim()) return
  try {
    selected.value = await store.changeMemory(selected.value.id, correctionDraft.value.trim())
  } catch {
    // The store exposes the structured error below.
  }
}

function formatTime(value: string): string {
  if (!value) return '未知'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

onMounted(() => void refresh())
</script>

<template>
  <main
    class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 sm:p-4 lg:overflow-hidden"
    data-testid="memory-workspace"
  >
    <header class="flex shrink-0 flex-wrap items-start justify-between gap-3 px-1">
      <div>
        <h1 class="text-base font-semibold">记忆治理</h1>
        <p class="mt-1 text-xs text-c-text-muted">
          整理、审计和修正长期信息，不在聊天工具栏重复操作
        </p>
      </div>
      <button class="btn-accent" type="button" :disabled="organizing" @click="organize">
        {{ organizing ? '整理中' : '整理记忆' }}
      </button>
    </header>

    <section v-if="store.job" class="glass shrink-0 px-4 py-3" aria-live="polite">
      <div class="flex items-center justify-between gap-3 text-xs">
        <span class="text-c-text-secondary">{{ store.job.text || '记忆整理任务' }}</span>
        <span class="font-mono uppercase text-c-text-muted"
          >{{ store.job.status }} · {{ store.job.progress }}%</span
        >
      </div>
      <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-c-panel">
        <div
          class="h-full rounded-full bg-c-accent transition-all duration-300"
          :style="{ width: `${store.job.progress}%` }"
        />
      </div>
      <p v-if="store.job.error" class="mt-2 text-xs text-c-error">{{ store.job.error }}</p>
    </section>

    <section class="glass flex min-h-0 flex-1 flex-col overflow-hidden">
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b border-c-border p-3">
        <input
          :value="store.searchQuery"
          class="min-w-44 flex-1 rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-sm outline-none focus:border-c-border-accent"
          placeholder="搜索标题、摘要或正文"
          @input="store.setSearch(($event.target as HTMLInputElement).value)"
        />
        <select
          :value="store.filterType ?? ''"
          class="rounded-xl border border-c-border bg-c-panel px-3 py-2 text-xs"
          @change="selectType(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="item in types" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <select
          :value="store.filterScope ?? ''"
          class="rounded-xl border border-c-border bg-c-panel px-3 py-2 text-xs"
          @change="selectScope(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="item in scopes" :key="item.id" :value="item.id">{{ item.label }}</option>
        </select>
        <div
          class="flex rounded-xl border border-c-border bg-c-panel/45 p-1"
          role="group"
          aria-label="记忆视图"
        >
          <button
            class="rounded-lg px-2.5 py-1 text-xs"
            :class="view === 'list' ? 'bg-c-accent-soft text-c-accent' : 'text-c-text-muted'"
            type="button"
            :aria-pressed="view === 'list'"
            @click="view = 'list'"
          >
            列表
          </button>
          <button
            class="rounded-lg px-2.5 py-1 text-xs"
            :class="view === 'graph' ? 'bg-c-accent-soft text-c-accent' : 'text-c-text-muted'"
            type="button"
            :aria-pressed="view === 'graph'"
            @click="view = 'graph'"
          >
            关系图
          </button>
        </div>
        <button v-if="store.invalidated" class="btn-ghost" type="button" @click="refresh()">
          载入新版本
        </button>
      </div>

      <p
        v-if="store.error"
        class="m-3 rounded-xl border border-c-error/40 bg-c-error/10 px-3 py-2 text-xs text-c-error"
        role="alert"
      >
        {{ store.error.message }}
        <button class="ml-2 underline" type="button" @click="refresh()">重试</button>
      </p>

      <div class="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]">
        <div class="min-h-0 overflow-hidden border-b border-c-border lg:border-b-0 lg:border-r">
          <div
            v-if="store.loading"
            class="grid h-full min-h-80 place-items-center text-sm text-c-text-muted"
          >
            正在读取记忆
          </div>
          <div
            v-else-if="!store.filteredPages.length"
            class="grid h-full min-h-80 place-items-center px-6 text-center"
          >
            <div>
              <p class="text-sm text-c-text-secondary">没有符合条件的记忆</p>
              <p class="mt-1 text-xs text-c-text-muted">调整搜索、类型或作用域后重试</p>
            </div>
          </div>
          <div v-else-if="view === 'list'" class="h-full overflow-y-auto">
            <button
              v-for="page in store.filteredPages"
              :key="page.id"
              type="button"
              class="block w-full border-b border-c-border px-5 py-4 text-left transition-colors duration-200"
              :class="selected?.id === page.id ? 'bg-c-panel/55' : 'hover:bg-c-panel/30'"
              @click="selectPage(page)"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium">{{ page.title }}</p>
                  <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-c-text-secondary">
                    {{ page.summary || page.content }}
                  </p>
                </div>
                <span
                  v-if="page.retention_policy === 'pinned'"
                  class="rounded-lg bg-c-accent-soft px-2 py-1 text-10px text-c-accent"
                  >已固定</span
                >
              </div>
              <div class="mt-3 flex flex-wrap gap-2 text-10px text-c-text-muted">
                <span>{{ page.page_type }}</span
                ><span>{{ page.scope }}</span
                ><span>v{{ page.version }}</span
                ><span>{{ formatTime(page.updated_at) }}</span>
              </div>
            </button>
            <div v-if="store.nextCursor" class="p-4 text-center">
              <button class="btn-ghost" type="button" @click="refresh(true)">加载更多</button>
            </div>
          </div>
          <MemoryGraph
            v-else
            class="h-full min-h-112"
            :pages="store.filteredPages"
            @node-click="selectGraphNode"
          />
        </div>

        <aside class="min-h-0 overflow-y-auto p-5">
          <div v-if="!selected" class="grid min-h-72 place-items-center text-center">
            <div>
              <p class="text-sm text-c-text-secondary">选择一条记忆查看详情</p>
              <p class="mt-1 text-xs text-c-text-muted">关系、审计信息和修正入口集中在这里</p>
            </div>
          </div>
          <template v-else>
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h2 class="break-words text-sm font-semibold">{{ selected.title }}</h2>
                <p class="mt-1 font-mono text-10px text-c-text-muted">{{ selected.id }}</p>
              </div>
              <button class="btn-ghost" type="button" @click="togglePin(selected)">
                {{ selected.retention_policy === 'pinned' ? '取消固定' : '固定' }}
              </button>
            </div>

            <p class="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-c-text-secondary">
              {{ selected.content }}
            </p>

            <div class="mt-5">
              <h3 class="text-xs font-medium">关系</h3>
              <ul
                v-if="selected.relations.length"
                class="mt-2 space-y-2 text-xs text-c-text-secondary"
              >
                <li
                  v-for="relation in selected.relations"
                  :key="`${relation.source_id}:${relation.target_id}:${relation.relation_type}`"
                  class="rounded-xl bg-c-panel/45 px-3 py-2"
                >
                  {{ relation.relation_type }} · {{ relation.target_id }}
                </li>
              </ul>
              <p v-else class="mt-2 text-xs text-c-text-muted">暂无已建立关系</p>
            </div>

            <dl class="mt-5 grid grid-cols-2 gap-2 text-xs">
              <div class="rounded-xl bg-c-panel/45 p-3">
                <dt class="text-c-text-muted">可信度</dt>
                <dd class="mt-1 font-mono">{{ selected.confidence }}</dd>
              </div>
              <div class="rounded-xl bg-c-panel/45 p-3">
                <dt class="text-c-text-muted">信任等级</dt>
                <dd class="mt-1 font-mono">{{ selected.trust_level }}</dd>
              </div>
              <div class="rounded-xl bg-c-panel/45 p-3">
                <dt class="text-c-text-muted">索引状态</dt>
                <dd class="mt-1 font-mono">{{ selected.index_state }}</dd>
              </div>
              <div class="rounded-xl bg-c-panel/45 p-3">
                <dt class="text-c-text-muted">可见性</dt>
                <dd class="mt-1 font-mono">{{ selected.visibility }}</dd>
              </div>
            </dl>

            <label class="mt-5 block text-xs font-medium">
              内容修正
              <textarea
                v-model="correctionDraft"
                rows="4"
                class="mt-2 w-full resize-none rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-sm font-normal outline-none focus:border-c-border-accent"
              />
            </label>
            <div class="mt-3 flex flex-wrap gap-2">
              <button
                class="btn-accent"
                type="button"
                :disabled="!correctionDraft.trim()"
                @click="saveCorrection"
              >
                保存修正
              </button>
              <button
                class="btn-ghost"
                type="button"
                @click="emit('send-to-sandbox', selected.content)"
              >
                发送到对话沙盒
              </button>
              <button class="btn-ghost text-c-error" type="button" @click="forget(selected)">
                {{ confirmForgetId === selected.id ? '确认遗忘' : '遗忘' }}
              </button>
            </div>
          </template>
        </aside>
      </div>
    </section>
  </main>
</template>

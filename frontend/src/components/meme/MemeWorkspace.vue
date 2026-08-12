<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { fetchCommandTask, readCommandTask, startCommandTask } from '@/composables/commandTasks'
import { Events } from '@/constants/socket-events'

interface MemeItem {
  id: string
  text: string
  context_hint: string
  tags: string[]
  source_platform: string
  base_score: number
  cognitive_analysis?: {
    humor_mechanism?: string
    emotional_tone?: string
    persona_fit_score?: number
    source_url?: string
  } | null
}

type RequestState = 'idle' | 'loading' | 'error'

const items = ref<MemeItem[]>([])
const currentIndex = ref(0)
const source = ref('')
const state = ref<RequestState>('idle')
const collecting = ref(false)
const error = ref('')
const notice = ref('')
const feedback = ref('')
const goodCount = ref(0)
const badCount = ref(0)
const manualText = ref('')
const manualUrl = ref('')
const adding = ref(false)
const downloadUrl = ref('')
let collectListener:
  ((payload: { ok?: boolean; task_id?: string; count?: number; error?: string }) => void) | null =
  null

const current = computed(() => items.value[currentIndex.value] ?? null)
const isDone = computed(() => items.value.length > 0 && currentIndex.value >= items.value.length)
const progress = computed(() =>
  items.value.length
    ? `${Math.min(currentIndex.value + 1, items.value.length)} / ${items.value.length}`
    : '0 / 0',
)

function connectedSocket() {
  const socket = getSocket()
  if (!socket?.connected) {
    error.value = '服务未连接，无法读取 Meme 梗库'
    return null
  }
  return socket
}

function loadCandidates(): void {
  const socket = connectedSocket()
  if (!socket) {
    state.value = 'error'
    return
  }
  state.value = 'loading'
  error.value = ''
  socket.emit(
    Events.MEME.LIST,
    { source_platform: source.value, limit: 50 },
    (payload: { memes?: MemeItem[]; error?: string }) => {
      if (payload?.error) {
        state.value = 'error'
        error.value = payload.error
        return
      }
      items.value = payload?.memes ?? []
      currentIndex.value = 0
      state.value = 'idle'
    },
  )
}

function collectCandidates(): void {
  const socket = connectedSocket()
  if (!socket || collecting.value) return
  const isRetry = Boolean(error.value)
  collecting.value = true
  error.value = ''
  const taskId = startCommandTask(
    'meme.collect',
    source.value || 'bilibili',
    window.localStorage,
    () => crypto.randomUUID(),
    isRetry,
  )
  socket
    .timeout(120_000)
    .emit(
      Events.MEME.COLLECT,
      { task_id: taskId, source: source.value || 'bilibili' },
      (timeoutError: Error | null, payload?: { ok?: boolean; count?: number; error?: string }) => {
        collecting.value = false
        if (timeoutError) {
          error.value = '采集超时，请重试'
          return
        }
        if (!payload?.ok) {
          error.value = payload?.error || '采集失败'
          return
        }
        notice.value = `采集完成，新增 ${payload.count ?? 0} 个候选`
        loadCandidates()
      },
    )
}

async function recoverCollection(): Promise<void> {
  const socket = connectedSocket()
  const persisted = readCommandTask('meme.collect')
  if (!socket || !persisted) return
  const snapshot = await fetchCommandTask(socket, 'meme.collect', persisted.taskId)
  if (!snapshot) return
  if (snapshot.status === 'accepted' || snapshot.status === 'processing') {
    collecting.value = true
    notice.value = '已恢复采集任务，等待完成'
    if (collectListener) socket.off(Events.MEME.COLLECT, collectListener)
    const listener = (payload: {
      ok?: boolean
      task_id?: string
      count?: number
      error?: string
    }) => {
      if (payload?.task_id !== persisted.taskId) return
      collecting.value = false
      socket.off(Events.MEME.COLLECT, listener)
      collectListener = null
      if (!payload.ok) {
        error.value = payload.error || '采集失败'
        return
      }
      notice.value = `采集完成，新增 ${payload.count ?? 0} 个候选`
      loadCandidates()
    }
    collectListener = listener
    socket.on(Events.MEME.COLLECT, collectListener)
  } else if (snapshot.status === 'succeeded') {
    notice.value = '已恢复上次采集结果'
    loadCandidates()
  } else if (snapshot.status === 'interrupted') {
    error.value = '服务重启，原采集结果未知；重试会创建新任务。'
  } else if (snapshot.status === 'failed' || snapshot.status === 'cancelled') {
    error.value = snapshot.error?.message || '上次采集未完成；重试会创建新任务。'
  }
}

function addManual(): void {
  const text = manualText.value.trim()
  const socket = connectedSocket()
  if (!socket || !text || adding.value) return
  adding.value = true
  error.value = ''
  socket.emit(
    Events.MEME.ADD,
    {
      text,
      source: 'user',
      source_url: manualUrl.value.trim(),
      context_hint: '后台手动添加',
    },
    (payload: { ok?: boolean; error?: string }) => {
      adding.value = false
      if (!payload?.ok) {
        error.value = payload?.error || '添加失败'
        return
      }
      manualText.value = ''
      manualUrl.value = ''
      notice.value = '候选已加入梗库'
      loadCandidates()
    },
  )
}

function next(): void {
  feedback.value = ''
  currentIndex.value = Math.min(currentIndex.value + 1, items.value.length)
}

function previous(): void {
  feedback.value = ''
  currentIndex.value = Math.max(currentIndex.value - 1, 0)
}

function review(status: 'good' | 'bad'): void {
  const socket = connectedSocket()
  if (!socket || !current.value) return
  socket.emit(
    Events.MEME.REVIEW,
    { meme_id: current.value.id, status },
    (payload: { ok?: boolean; feedback?: string; error?: string }) => {
      if (!payload?.ok) {
        error.value = payload?.error || '审核失败'
        return
      }
      if (status === 'good') goodCount.value += 1
      else badCount.value += 1
      feedback.value = payload.feedback || (status === 'good' ? '已通过' : '已拒绝')
      currentIndex.value = Math.min(currentIndex.value + 1, items.value.length)
    },
  )
}

function exportDataset(): void {
  const socket = connectedSocket()
  if (!socket) return
  socket.emit(Events.MEME.DATASET, {}, (payload: { memes?: unknown[]; error?: string }) => {
    if (payload?.error) {
      error.value = payload.error
      return
    }
    downloadUrl.value = `data:application/json;charset=utf-8,${encodeURIComponent(
      JSON.stringify(payload?.memes ?? [], null, 2),
    )}`
  })
}

onMounted(() => {
  loadCandidates()
  void recoverCollection()
})

onBeforeUnmount(() => {
  const socket = getSocket()
  if (socket && collectListener) socket.off(Events.MEME.COLLECT, collectListener)
})
</script>

<template>
  <section
    class="grid min-h-full gap-3 lg:grid-cols-[minmax(280px,2fr)_minmax(0,5fr)]"
    data-testid="meme-workspace"
  >
    <aside class="glass h-fit overflow-hidden">
      <header class="border-b border-c-border px-5 py-4">
        <h1 class="text-sm font-semibold">候选来源</h1>
        <p class="mt-1 text-xs text-c-text-muted">采集和手动添加只归属于 Meme 梗库</p>
      </header>
      <div class="space-y-4 p-5">
        <label class="block text-xs text-c-text-secondary">
          来源过滤
          <select
            v-model="source"
            class="mt-2 w-full rounded-xl border border-c-border bg-c-panel px-3 py-2 text-sm"
            @change="loadCandidates"
          >
            <option value="">全部来源</option>
            <option value="bilibili">Bilibili</option>
            <option value="user">手动添加</option>
          </select>
        </label>
        <div class="grid grid-cols-2 gap-2">
          <button
            class="btn-accent"
            type="button"
            :disabled="collecting"
            @click="collectCandidates"
          >
            {{ collecting ? '采集中' : '采集热梗' }}
          </button>
          <button
            class="btn-ghost"
            type="button"
            :disabled="state === 'loading'"
            @click="loadCandidates"
          >
            刷新
          </button>
        </div>

        <div class="border-t border-c-border pt-4">
          <h2 class="text-xs font-medium">手动添加候选</h2>
          <textarea
            v-model="manualText"
            rows="3"
            class="mt-2 w-full resize-none rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-sm outline-none focus:border-c-border-accent"
            placeholder="输入梗文本"
          />
          <input
            v-model="manualUrl"
            class="mt-2 w-full rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-xs outline-none focus:border-c-border-accent"
            placeholder="来源链接，可选"
          />
          <button
            class="btn-ghost mt-2 w-full"
            type="button"
            :disabled="!manualText.trim() || adding"
            @click="addManual"
          >
            {{ adding ? '分析中' : '添加并分析' }}
          </button>
        </div>
      </div>
    </aside>

    <div class="glass flex min-h-136 flex-col overflow-hidden">
      <header
        class="flex flex-wrap items-start justify-between gap-3 border-b border-c-border px-5 py-4"
      >
        <div>
          <h2 class="text-sm font-semibold">候选审核</h2>
          <p class="mt-1 text-xs text-c-text-muted">
            {{ progress }} · 通过 {{ goodCount }} · 拒绝 {{ badCount }}
          </p>
        </div>
        <div class="flex gap-2">
          <button class="btn-ghost" type="button" @click="exportDataset">准备导出</button>
          <a v-if="downloadUrl" class="btn-accent" :href="downloadUrl" download="meme_dataset.json"
            >下载数据集</a
          >
        </div>
      </header>

      <p
        v-if="error"
        class="m-4 rounded-xl border border-c-error/40 bg-c-error/10 px-3 py-2 text-xs text-c-error"
        role="alert"
      >
        {{ error }}
        <button class="ml-2 underline" type="button" @click="loadCandidates">重试</button>
      </p>
      <p
        v-if="notice"
        class="mx-4 mt-4 rounded-xl border border-c-success/30 bg-c-success/10 px-3 py-2 text-xs text-c-success"
        aria-live="polite"
      >
        {{ notice }}
      </p>

      <div
        v-if="state === 'loading'"
        class="grid min-h-80 flex-1 place-items-center text-sm text-c-text-muted"
      >
        正在加载候选
      </div>
      <div
        v-else-if="!items.length"
        class="grid min-h-80 flex-1 place-items-center px-6 text-center"
      >
        <div>
          <p class="text-sm text-c-text-secondary">当前来源没有待审核候选</p>
          <p class="mt-1 text-xs text-c-text-muted">可以采集热梗、手动添加或切换来源</p>
        </div>
      </div>
      <div v-else-if="isDone" class="grid min-h-80 flex-1 place-items-center px-6 text-center">
        <div>
          <p class="text-sm text-c-text-secondary">全部候选已处理</p>
          <p class="mt-1 text-xs text-c-text-muted">
            通过 {{ goodCount }} 条，拒绝 {{ badCount }} 条
          </p>
          <button class="btn-ghost mt-4" type="button" @click="loadCandidates">重新加载</button>
        </div>
      </div>
      <article v-else-if="current" class="flex-1 overflow-y-auto p-5">
        <div class="rounded-xl border border-c-border bg-c-card/45 p-5">
          <p class="text-lg font-medium leading-relaxed">{{ current.text }}</p>
          <p v-if="current.context_hint" class="mt-3 text-xs leading-relaxed text-c-text-secondary">
            {{ current.context_hint }}
          </p>
          <div class="mt-4 flex flex-wrap gap-2 text-10px">
            <span class="rounded-lg bg-c-accent-soft px-2 py-1 text-c-accent">{{
              current.source_platform || 'unknown'
            }}</span>
            <span
              v-for="tag in current.tags"
              :key="tag"
              class="rounded-lg bg-c-panel px-2 py-1 text-c-text-secondary"
              >{{ tag }}</span
            >
          </div>
          <dl class="mt-5 grid gap-3 text-xs sm:grid-cols-3">
            <div class="rounded-xl bg-c-panel/45 p-3">
              <dt class="text-c-text-muted">幽默机制</dt>
              <dd class="mt-1">{{ current.cognitive_analysis?.humor_mechanism || '待分析' }}</dd>
            </div>
            <div class="rounded-xl bg-c-panel/45 p-3">
              <dt class="text-c-text-muted">情绪倾向</dt>
              <dd class="mt-1">{{ current.cognitive_analysis?.emotional_tone || '待分析' }}</dd>
            </div>
            <div class="rounded-xl bg-c-panel/45 p-3">
              <dt class="text-c-text-muted">人格匹配</dt>
              <dd class="mt-1 font-mono">
                {{
                  current.cognitive_analysis?.persona_fit_score == null
                    ? '待分析'
                    : `${Math.round(current.cognitive_analysis.persona_fit_score * 100)}%`
                }}
              </dd>
            </div>
          </dl>
          <a
            v-if="current.cognitive_analysis?.source_url"
            class="mt-4 inline-block text-xs text-c-accent underline"
            :href="current.cognitive_analysis.source_url"
            target="_blank"
            rel="noreferrer"
            >查看来源</a
          >
        </div>
        <p
          v-if="feedback"
          class="mt-3 rounded-xl border border-c-border bg-c-panel/45 px-4 py-3 text-xs text-c-text-secondary"
          aria-live="polite"
        >
          最近审核反馈：{{ feedback }}
        </p>
      </article>

      <footer
        v-if="current && !isDone"
        class="flex flex-wrap items-center gap-2 border-t border-c-border bg-c-surface/55 p-4"
      >
        <button class="btn-ghost" type="button" :disabled="currentIndex === 0" @click="previous">
          上一条
        </button>
        <button class="btn-ghost" type="button" @click="next">跳过</button>
        <span class="flex-1" />
        <button class="btn-ghost text-c-error" type="button" @click="review('bad')">拒绝</button>
        <button class="btn-accent" type="button" @click="review('good')">通过</button>
      </footer>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  controlProgramReplay,
  getProgramReplay,
  getProgramVersion,
  listProgramScripts,
  startProgramReplay,
  type ProgramScript,
  type ProgramScriptSummary,
  type ReplaySnapshot,
} from '@/services/programScripts'

const creatorId = 'dashboard'
const scripts = ref<ProgramScriptSummary[]>([])
const selected = ref('')
const loadedScript = ref<ProgramScript | null>(null)
const selections = ref<Record<string, string>>({})
const source = ref<'script' | 'jsonl'>('script')
const jsonl = ref('')
const roomId = ref(1)
const speed = ref(1)
const replay = ref<ReplaySnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const publishedChoices = computed(() =>
  scripts.value.flatMap((script) =>
    script.archived
      ? []
      : script.versions.map((version) => ({
          key: `${script.id}@${version}`,
          id: script.id,
          version,
          label: `${script.title} · v${version}${script.builtin ? ' · 内置' : ''}`,
        })),
  ),
)
const selectableSlots = computed(() => {
  if (!loadedScript.value) return []
  const seen = new Set<string>()
  return loadedScript.value.beats.flatMap((beat) => {
    const slot = beat.input.save_as
    const setId = beat.input.options
    if (!slot || !setId || seen.has(slot) || !loadedScript.value?.option_sets[setId]) return []
    seen.add(slot)
    return [{ slot, options: loadedScript.value.option_sets[setId] }]
  })
})
const isActive = computed(() => ['running', 'paused'].includes(replay.value?.state ?? ''))
const progress = computed(() =>
  replay.value?.total_events
    ? Math.round((replay.value.cursor / replay.value.total_events) * 100)
    : 0,
)
const currentBeatId = computed(() => {
  const context = replay.value?.current_event?.payload.program_context
  if (!context || typeof context !== 'object') return null
  const beatId = (context as Record<string, unknown>).program_beat_id
  return typeof beatId === 'string' ? beatId : null
})
const canStart = computed(() => {
  if (loading.value || isActive.value) return false
  if (source.value === 'jsonl') return Boolean(jsonl.value.trim())
  return Boolean(selected.value && loadedScript.value)
})
const controlHint = computed(() => {
  if (loading.value) return '正在加载重放配置，请稍候。'
  if (source.value === 'jsonl' && !jsonl.value.trim()) return '粘贴或选择 JSONL 后即可开始重放。'
  if (source.value === 'script' && !loadedScript.value)
    return '选择并加载已发布脚本后即可开始重放。'
  if (!replay.value || ['completed', 'stopped', 'failed'].includes(replay.value.state))
    return '开始重放后可使用暂停、调速和重新开始；继续和单步仅在暂停时可用。'
  if (replay.value.state === 'paused') return '重放已暂停，可以继续、单步、调速或重新开始。'
  return '重放进行中，可以暂停、调速、重新开始或停止。'
})

onMounted(async () => {
  await refreshScripts()
  pollTimer = setInterval(() => void poll(), 500)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

watch(selected, () => void loadSelectedScript())

async function refreshScripts() {
  await act(async () => {
    scripts.value = await listProgramScripts()
    selected.value ||= publishedChoices.value[0]?.key ?? ''
    await loadSelectedScript()
  })
}

async function loadSelectedScript() {
  const choice = publishedChoices.value.find((item) => item.key === selected.value)
  if (!choice) return
  try {
    loadedScript.value = (await getProgramVersion(choice.id, choice.version)).script
    for (const entry of selectableSlots.value)
      selections.value[entry.slot] ||= entry.options[0]?.id ?? ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function start() {
  const choice = publishedChoices.value.find((item) => item.key === selected.value)
  if (source.value === 'script' && !choice) return
  await act(async () => {
    replay.value = await startProgramReplay(
      source.value === 'script'
        ? {
            source: 'script',
            script_id: choice!.id,
            version: choice!.version,
            selections: selections.value,
            room_id: roomId.value,
            creator_id: creatorId,
            speed: speed.value,
          }
        : {
            source: 'jsonl',
            jsonl: jsonl.value,
            room_id: roomId.value,
            creator_id: creatorId,
            speed: speed.value,
          },
    )
  })
}

async function control(action: 'pause' | 'resume' | 'step' | 'speed' | 'restart' | 'stop') {
  if (!replay.value) return
  await act(async () => {
    replay.value = await controlProgramReplay(
      replay.value!.replay_id,
      action,
      creatorId,
      action === 'speed' || action === 'restart' ? speed.value : undefined,
    )
  })
}

async function poll() {
  if (!replay.value || !isActive.value) return
  try {
    replay.value = await getProgramReplay(replay.value.replay_id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  }
}

async function readFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) jsonl.value = await file.text()
}

async function act(operation: () => Promise<void>) {
  loading.value = true
  error.value = ''
  try {
    await operation()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="space-y-3" aria-label="弹幕重放控制台">
    <div class="glass p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold">重放来源</h2>
          <p class="mt-1 text-xs text-c-text-muted">事件仍经过真实直播、Aura 与 memory v2 链路</p>
        </div>
        <div class="flex rounded-xl border border-c-border bg-c-panel p-1">
          <button
            class="cursor-pointer rounded-xl px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
            :class="source === 'script' ? 'bg-c-accent-soft text-c-accent' : 'text-c-text-muted'"
            :disabled="isActive"
            @click="source = 'script'"
          >
            脚本版本
          </button>
          <button
            class="cursor-pointer rounded-xl px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
            :class="source === 'jsonl' ? 'bg-c-accent-soft text-c-accent' : 'text-c-text-muted'"
            :disabled="isActive"
            @click="source = 'jsonl'"
          >
            JSONL
          </button>
        </div>
      </div>

      <div v-if="source === 'script'" class="mt-4 grid gap-3 md:grid-cols-2">
        <label class="text-xs text-c-text-dim"
          >已发布脚本<select v-model="selected" class="form-control mt-1" :disabled="isActive">
            <option v-for="choice in publishedChoices" :key="choice.key" :value="choice.key">
              {{ choice.label }}
            </option>
          </select></label
        >
        <div class="text-xs text-c-text-dim">
          预设答案组合
          <div class="mt-1 grid gap-2 sm:grid-cols-2">
            <label
              v-for="entry in selectableSlots"
              :key="entry.slot"
              class="rounded-xl border border-c-border bg-c-panel/40 p-2"
              ><span class="font-mono text-10px">{{ entry.slot }}</span
              ><select
                v-model="selections[entry.slot]"
                class="form-control mt-1"
                :disabled="isActive"
              >
                <option v-for="option in entry.options" :key="option.id" :value="option.id">
                  {{ option.label }}
                </option>
              </select></label
            >
          </div>
        </div>
      </div>
      <div v-else class="mt-4 space-y-2">
        <label class="text-xs text-c-text-dim"
          >选择 JSONL 文件<input
            type="file"
            accept=".jsonl,application/json"
            class="mt-1 block text-xs"
            :disabled="isActive"
            @change="readFile"
        /></label>
        <label class="text-xs text-c-text-dim"
          >或粘贴 JSONL<textarea
            v-model="jsonl"
            class="form-control mt-1 min-h-44 font-mono text-xs"
            :disabled="isActive"
            placeholder='{"offset_ms":0,"event_type":"danmaku","actor_id":"测试观众","text":"你好"}'
          />
        </label>
      </div>

      <div class="mt-4 flex flex-wrap items-end gap-3">
        <label class="w-28 text-xs text-c-text-dim"
          >房间<input
            v-model.number="roomId"
            type="number"
            min="1"
            class="form-control mt-1"
            :disabled="isActive"
        /></label>
        <label class="w-32 text-xs text-c-text-dim"
          >速度<select v-model.number="speed" class="form-control mt-1">
            <option :value="0.5">0.5×</option>
            <option :value="1">1×</option>
            <option :value="2">2×</option>
            <option :value="5">5×</option>
            <option :value="10">10×</option>
          </select></label
        >
        <button
          class="btn-accent"
          :disabled="!canStart"
          aria-describedby="program-replay-control-hint"
          @click="start"
        >
          开始
        </button>
        <button
          class="btn-ghost border border-c-border"
          :disabled="loading || replay?.state !== 'running'"
          aria-describedby="program-replay-control-hint"
          @click="control('pause')"
        >
          暂停
        </button>
        <button
          class="btn-ghost border border-c-border"
          :disabled="loading || replay?.state !== 'paused'"
          aria-describedby="program-replay-control-hint"
          @click="control('resume')"
        >
          继续
        </button>
        <button
          class="btn-ghost border border-c-border"
          :disabled="loading || replay?.state !== 'paused'"
          aria-describedby="program-replay-control-hint"
          @click="control('step')"
        >
          单步
        </button>
        <button
          class="btn-ghost border border-c-border"
          :disabled="loading || !replay"
          aria-describedby="program-replay-control-hint"
          @click="control('speed')"
        >
          应用速度
        </button>
        <button
          class="btn-ghost border border-c-border"
          :disabled="loading || !replay"
          aria-describedby="program-replay-control-hint"
          @click="control('restart')"
        >
          重新开始
        </button>
        <button
          class="btn-ghost border border-c-error/40 text-c-error"
          :disabled="loading || !isActive"
          aria-describedby="program-replay-control-hint"
          @click="control('stop')"
        >
          停止
        </button>
      </div>
      <p id="program-replay-control-hint" class="mt-2 text-xs text-c-text-muted" aria-live="polite">
        {{ controlHint }}
      </p>
    </div>

    <div v-if="replay" class="glass p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold">重放进度</h2>
          <p class="mt-1 font-mono text-xs text-c-text-muted">{{ replay.replay_id }}</p>
        </div>
        <span
          class="rounded-xl bg-c-accent-soft px-2 py-1 font-mono text-xs uppercase text-c-accent"
          >{{ replay.state }}</span
        >
      </div>
      <div class="mt-4 h-2 overflow-hidden rounded-xl bg-c-panel">
        <div
          class="h-full rounded-xl bg-c-accent transition-[width] duration-200"
          :style="{ width: `${progress}%` }"
        />
      </div>
      <div class="mt-2 flex justify-between text-xs text-c-text-muted">
        <span>已投递 {{ replay.cursor }} / {{ replay.total_events }}</span
        ><span>{{ progress }}%</span>
      </div>
      <article class="mt-4 rounded-xl border border-c-border bg-c-panel/35 p-4">
        <p class="text-10px uppercase text-c-text-muted">当前事件 / 等待原因</p>
        <template v-if="replay.current_event"
          ><div class="mt-2 flex flex-wrap gap-2 font-mono text-xs text-c-text-muted">
            <span>#{{ replay.current_event.sequence + 1 }}</span
            ><span>{{ replay.current_event.offset_ms }}ms</span
            ><span>{{ replay.current_event.event_type }}</span
            ><span>{{ replay.current_event.actor_id }}</span
            ><span v-if="currentBeatId">当前题 {{ currentBeatId }}</span>
          </div>
          <p class="mt-2 text-sm text-c-text">
            {{ replay.current_event.text || '非弹幕事件，等待按时间投递' }}
          </p></template
        >
        <p v-else class="mt-2 text-sm text-c-text-secondary">
          {{
            replay.state === 'completed'
              ? '全部事件已投递'
              : replay.state === 'paused'
                ? '已暂停，等待继续或单步'
                : '等待启动'
          }}
        </p>
      </article>
      <p v-if="replay.error" class="mt-3 text-xs text-c-error">{{ replay.error }}</p>
    </div>

    <p
      v-if="error"
      class="rounded-xl border border-c-error/40 bg-c-error/10 px-3 py-2 text-xs text-c-error"
      role="alert"
    >
      {{ error }}
    </p>
  </section>
</template>

<style scoped>
.form-control {
  width: 100%;
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  background: var(--c-panel);
  padding: 0.5rem 0.75rem;
  color: var(--c-text);
  font-size: 0.875rem;
  outline: none;
  transition: border-color 200ms var(--ease-out-expo);
}

.form-control:focus {
  border-color: var(--c-border-accent);
}
</style>

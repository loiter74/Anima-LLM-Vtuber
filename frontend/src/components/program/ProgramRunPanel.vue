<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  controlProgramRun,
  getCurrentProgramRun,
  getProgramRun,
  listProgramScripts,
  startProgramRun,
  submitProgramChoice,
  type ProgramRunSnapshot,
  type ProgramScriptSummary,
} from '@/services/programScripts'
import { fetchCommandTask, readCommandTask, startCommandTask } from '@/composables/commandTasks'
import { getSocket } from '@/composables/useSocket'

const creatorId = 'dashboard'
const roomId = ref(1)
const scripts = ref<ProgramScriptSummary[]>([])
const selected = ref('')
const run = ref<ProgramRunSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const phaseLabels = { qi: '起', cheng: '承', zhuan: '转', he: '合' } as const
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
const isActive = computed(() => ['running', 'paused'].includes(run.value?.state ?? ''))
const currentCopy = computed(
  () =>
    run.value?.current_beat?.host_prompt || run.value?.current_beat?.viewer_prompt || '准备收官',
)
const controlHint = computed(() => {
  if (loading.value) return '正在处理现场控制命令，请稍候。'
  if (!publishedChoices.value.length) return '暂无可运行的已发布脚本。'
  if (!run.value || ['completed', 'stopped'].includes(run.value.state))
    return '开始节目后可使用暂停和停止；重试仅在暂停或失败时可用。'
  if (run.value.state === 'paused') return '节目已暂停，可以继续、重试当前轮或停止。'
  if (run.value.state === 'failed') return '当前轮执行失败，可以重试当前轮。'
  return '节目运行中，可以暂停或停止。'
})

onMounted(async () => {
  await refreshScripts()
  await refreshCurrent()
  await recoverStart()
  pollTimer = setInterval(() => void pollRun(), 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function refreshScripts() {
  try {
    scripts.value = await listProgramScripts()
    selected.value ||= publishedChoices.value[0]?.key ?? ''
  } catch (reason) {
    error.value = String(reason)
  }
}

async function refreshCurrent() {
  try {
    run.value = await getCurrentProgramRun(roomId.value)
  } catch (reason) {
    error.value = String(reason)
  }
}

async function recoverStart() {
  if (run.value) return
  const socket = getSocket()
  const persisted = readCommandTask('program.start')
  if (!socket?.connected || !persisted) return
  const snapshot = await fetchCommandTask(socket, 'program.start', persisted.taskId)
  const recovered = snapshot?.result ?? snapshot?.progress
  if (recovered?.run_id) run.value = recovered as unknown as ProgramRunSnapshot
  else if (snapshot?.status === 'interrupted') {
    error.value = '服务重启，原节目运行结果未知；再次开始会创建新任务。'
  }
}

async function pollRun() {
  if (!run.value || !isActive.value) return
  try {
    run.value = await getProgramRun(run.value.run_id)
  } catch (reason) {
    error.value = String(reason)
  }
}

async function start() {
  const choice = publishedChoices.value.find((item) => item.key === selected.value)
  if (!choice) return
  await act(async () => {
    run.value = await startProgramRun({
      script_id: choice.id,
      version: choice.version,
      room_id: roomId.value,
      creator_id: creatorId,
      task_id: startCommandTask(
        'program.start',
        `${choice.id}@${choice.version}:${roomId.value}`,
        window.localStorage,
        () => crypto.randomUUID(),
        Boolean(error.value) ||
          Boolean(run.value && ['completed', 'stopped', 'failed'].includes(run.value.state)),
      ),
    })
  })
}

async function choose(optionId: string) {
  if (!run.value?.current_beat) return
  await act(async () => {
    run.value = await submitProgramChoice(
      run.value!.run_id,
      run.value!.current_beat!.id,
      optionId,
      creatorId,
      crypto.randomUUID(),
    )
  })
}

async function control(action: 'pause' | 'resume' | 'retry' | 'stop') {
  if (!run.value) return
  await act(async () => {
    run.value = await controlProgramRun(run.value!.run_id, action, creatorId, crypto.randomUUID())
  })
}

async function act(operation: () => Promise<void>) {
  loading.value = true
  error.value = ''
  try {
    await operation()
  } catch (reason) {
    error.value = String(reason)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="glass shrink-0 p-4" aria-label="节目现场运行">
    <div class="flex flex-wrap items-end gap-3">
      <label class="min-w-64 flex-1 text-xs text-c-text-dim">
        已发布脚本
        <select
          v-model="selected"
          class="mt-1 w-full rounded-xl border border-c-border bg-c-panel px-3 py-2 text-sm text-c-text outline-none focus:border-c-border-accent"
          :disabled="isActive"
        >
          <option v-for="choice in publishedChoices" :key="choice.key" :value="choice.key">
            {{ choice.label }}
          </option>
        </select>
      </label>
      <label class="w-28 text-xs text-c-text-dim">
        房间
        <input
          v-model.number="roomId"
          type="number"
          min="1"
          class="mt-1 w-full rounded-xl border border-c-border bg-c-panel px-3 py-2 text-sm text-c-text outline-none focus:border-c-border-accent"
          :disabled="isActive"
        />
      </label>
      <button
        class="btn-accent"
        :disabled="loading || isActive || !selected"
        aria-describedby="program-run-control-hint"
        @click="start"
      >
        开始
      </button>
      <button
        class="btn-ghost border border-c-border"
        :disabled="loading || !isActive"
        aria-describedby="program-run-control-hint"
        @click="control(run?.state === 'paused' ? 'resume' : 'pause')"
      >
        {{ run?.state === 'paused' ? '继续' : '暂停' }}
      </button>
      <button
        class="btn-ghost border border-c-border"
        :disabled="loading || !run || !['paused', 'failed'].includes(run.state)"
        aria-describedby="program-run-control-hint"
        @click="control('retry')"
      >
        重试当前轮
      </button>
      <button
        class="btn-ghost border border-c-error/40 text-c-error"
        :disabled="loading || !isActive"
        aria-describedby="program-run-control-hint"
        @click="control('stop')"
      >
        停止
      </button>
    </div>
    <p id="program-run-control-hint" class="mt-2 text-xs text-c-text-muted" aria-live="polite">
      {{ controlHint }}
    </p>

    <div v-if="run" class="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,1fr)]">
      <article class="rounded-xl border border-c-border bg-c-panel/45 p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded-xl bg-c-accent-soft px-2 py-1 text-xs text-c-accent">
            {{ run.current_beat ? phaseLabels[run.current_beat.phase] : '完成' }}
          </span>
          <span class="font-mono text-xs text-c-text-muted">
            {{ Math.min(run.current_index + 1, run.total_beats) }}/{{ run.total_beats }}
          </span>
          <span class="font-mono text-xs uppercase text-c-text-secondary">{{ run.state }}</span>
          <span class="text-xs text-c-text-muted">等待：{{ run.waiting_for }}</span>
        </div>
        <h3 class="mt-3 text-base font-semibold">{{ currentCopy }}</h3>
        <p v-if="run.current_beat?.lead_in" class="mt-2 text-sm text-c-accent">
          Creator 引子：{{ run.current_beat.lead_in }}
        </p>
        <p class="mt-2 text-xs text-c-text-muted">{{ run.disclosure }}</p>

        <div v-if="run.current_beat?.options.length" class="mt-4 flex flex-wrap gap-2">
          <button
            v-for="option in run.current_beat.options"
            :key="option.id"
            class="cursor-pointer rounded-xl border border-c-border bg-c-card px-3 py-2 text-sm transition-colors duration-200 hover:border-c-border-accent hover:text-c-accent disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-c-border disabled:hover:text-c-text"
            :disabled="loading || run.state !== 'running' || run.waiting_for !== 'choice'"
            @click="choose(option.id)"
          >
            {{ option.label }}
          </button>
        </div>
        <p v-if="run.error" class="mt-3 text-xs text-c-error" role="alert">{{ run.error }}</p>
      </article>

      <article class="max-h-52 overflow-y-auto rounded-xl border border-c-border bg-c-panel/30 p-4">
        <h3 class="text-xs font-medium text-c-text-dim">本轮记录</h3>
        <ol class="mt-2 space-y-2">
          <li
            v-for="record in run.records.slice().reverse()"
            :key="record.turn_id"
            class="flex items-start justify-between gap-3 text-xs"
          >
            <span class="font-mono text-c-text-muted">{{ record.beat_id }}</span>
            <span class="min-w-0 flex-1 truncate text-c-text-secondary">{{
              record.response_text
            }}</span>
            <span v-if="record.probe_result" class="font-mono text-c-accent">
              {{ record.probe_result }}
            </span>
          </li>
          <li v-if="!run.records.length" class="text-xs text-c-text-muted">尚无模型回复</li>
        </ol>
      </article>
    </div>
  </section>
</template>

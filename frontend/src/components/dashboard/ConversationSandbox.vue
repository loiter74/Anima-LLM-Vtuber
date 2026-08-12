<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { sendSandboxChatText } from '@/composables/chatTransport'
import { clearCommandTask, fetchCommandTask, startCommandTask } from '@/composables/commandTasks'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import { fetchRuntimeStatus } from '@/services/runtimeStatus'
import type {
  SandboxChunkEvent,
  SandboxHistoryMessage,
  SandboxRequestEvent,
} from '@/types/socket-events'

interface SandboxMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  status: 'complete' | 'streaming' | 'interrupted' | 'error'
  taskId?: string
}

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const messages = ref<SandboxMessage[]>([])
const isRecording = ref(false)
const isStreaming = ref(false)
const isSpeaking = ref(false)
const evidence = ref<Array<{ label: string; value: string }>>([])
const isCheckingRuntime = ref(false)
let sequence = 0
let activeCommand: SandboxRequestEvent | null = null
let startedAt = 0

const draft = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

function stopStream(status: 'complete' | 'interrupted'): void {
  if (status === 'interrupted' && activeCommand) {
    getSocket()?.emit(Events.CHAT.SANDBOX_CANCEL, activeCommand)
  }
  isStreaming.value = false
  isSpeaking.value = false
  let active: SandboxMessage | undefined
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    if (messages.value[index]?.status === 'streaming') {
      active = messages.value[index]
      break
    }
  }
  if (active) active.status = status
  if (status === 'interrupted') activeCommand = null
  if (status === 'interrupted') {
    window.sessionStorage.removeItem('animetta.sandbox.active-command')
    clearCommandTask('chat.sandbox', window.sessionStorage)
  }
}

async function runPrivateExercise(): Promise<void> {
  const text = draft.value.trim()
  if (!text || isStreaming.value) return
  const socket = getSocket()
  if (!socket?.connected) {
    evidence.value = [{ label: '错误', value: '后台服务未连接' }]
    return
  }
  isCheckingRuntime.value = true
  try {
    const status = await fetchRuntimeStatus()
    const llm = status.components.llm
    if (
      status.profile === 'test' ||
      llm.configured.provider === 'mock' ||
      llm.resolved.provider === 'mock'
    ) {
      evidence.value = [{ label: '错误', value: '当前运行时为测试模型，私密演练已阻止' }]
      return
    }
  } catch {
    evidence.value = [{ label: '错误', value: '无法确认当前模型身份' }]
    return
  } finally {
    isCheckingRuntime.value = false
  }

  const history: SandboxHistoryMessage[] = messages.value
    .filter((message) => message.status === 'complete' && message.text)
    .slice(-20)
    .map((message) => ({ role: message.role, content: message.text }))
  startedAt = performance.now()
  messages.value.push({ id: ++sequence, role: 'user', text, status: 'complete' })
  const response: SandboxMessage = {
    id: ++sequence,
    role: 'assistant',
    text: '',
    status: 'streaming',
  }
  messages.value.push(response)
  draft.value = ''
  isStreaming.value = true
  const requestKey = JSON.stringify({ text, history })
  const taskId = startCommandTask('chat.sandbox', requestKey, window.sessionStorage, () =>
    crypto.randomUUID(),
  )
  activeCommand = sendSandboxChatText(socket, text, history, {
    storage: window.localStorage,
    taskId,
  })
  window.sessionStorage.setItem('animetta.sandbox.active-command', JSON.stringify(activeCommand))
  response.taskId = activeCommand.task_id
}

function onSandboxChunk(payload: SandboxChunkEvent): void {
  if (!activeCommand || payload.task_id !== activeCommand.task_id) return
  const response = messages.value.find(
    (message) => message.role === 'assistant' && message.taskId === payload.task_id,
  )
  if (!response) return
  if (payload.text) response.text += payload.text
  evidence.value = [
    { label: '模型', value: [payload.provider, payload.model].filter(Boolean).join(' / ') },
    { label: '执行边界', value: '私密模型链路' },
    { label: '直播输出', value: '未接入（私密链路）' },
    { label: 'TTS / 记忆', value: '未接入（私密链路）' },
    { label: '耗时', value: `${Math.round(performance.now() - startedAt)} ms` },
  ]
  if (!payload.is_complete) return
  response.status = payload.error_code
    ? payload.error_code === 'interrupted'
      ? 'interrupted'
      : 'error'
    : 'complete'
  if (payload.error_code && payload.error_code !== 'interrupted') {
    response.text ||= `生成失败：${payload.error_code}`
  }
  isStreaming.value = false
  activeCommand = null
  window.sessionStorage.removeItem('animetta.sandbox.active-command')
  clearCommandTask('chat.sandbox', window.sessionStorage)
}

async function recoverActiveCommand(): Promise<void> {
  const socket = getSocket()
  const raw = window.sessionStorage.getItem('animetta.sandbox.active-command')
  if (!socket?.connected || !raw) return
  try {
    const command = JSON.parse(raw) as SandboxRequestEvent
    const snapshot = await fetchCommandTask(socket, 'chat.sandbox', command.task_id, {
      conversation_id: command.conversation_id,
    })
    if (!snapshot) return
    activeCommand = command
    const resultText = typeof snapshot.result?.text === 'string' ? snapshot.result.text : ''
    const status: SandboxMessage['status'] =
      snapshot.status === 'succeeded'
        ? 'complete'
        : snapshot.status === 'interrupted'
          ? 'interrupted'
          : snapshot.status === 'failed'
            ? 'error'
            : 'streaming'
    messages.value.push({
      id: ++sequence,
      role: 'assistant',
      text:
        resultText ||
        (snapshot.status === 'interrupted'
          ? '服务重启，原任务结果未知；请重新发送以创建新任务。'
          : snapshot.error?.message || ''),
      status,
      taskId: command.task_id,
    })
    isStreaming.value = status === 'streaming'
    if (!isStreaming.value) {
      activeCommand = null
      window.sessionStorage.removeItem('animetta.sandbox.active-command')
      clearCommandTask('chat.sandbox', window.sessionStorage)
    }
  } catch {
    window.sessionStorage.removeItem('animetta.sandbox.active-command')
    clearCommandTask('chat.sandbox', window.sessionStorage)
  }
}

function toggleRecording(): void {
  isRecording.value = !isRecording.value
  if (!isRecording.value && !draft.value.trim()) draft.value = '模拟语音输入已停止，等待编辑确认。'
}

function previewSpeech(): void {
  if (!messages.value.length || isStreaming.value) return
  isSpeaking.value = !isSpeaking.value
}

onMounted(() => {
  getSocket()?.on(Events.CHAT.SANDBOX_CHUNK, onSandboxChunk)
  void recoverActiveCommand()
})

onUnmounted(() => {
  getSocket()?.off(Events.CHAT.SANDBOX_CHUNK, onSandboxChunk)
})
</script>

<template>
  <section class="grid h-full min-h-0 gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]">
    <div class="glass flex min-h-0 flex-col overflow-hidden">
      <header class="shrink-0 border-b border-c-border px-5 py-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 class="text-sm font-semibold">私密对话演练</h1>
            <p class="mt-1 text-xs text-c-text-muted">
              调用当前运行时模型，不进入直播、语音或记忆链路
            </p>
          </div>
          <span
            class="rounded-lg border border-c-warning/40 bg-c-warning/10 px-2 py-1 text-10px text-c-warning"
          >
            私密模型
          </span>
        </div>
      </header>

      <div class="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
        <div v-if="!messages.length" class="grid min-h-52 place-items-center text-center">
          <div>
            <p class="text-sm text-c-text-secondary">尚无演练记录</p>
            <p class="mt-1 text-xs text-c-text-muted">可从记忆详情带入内容，也可以直接输入</p>
          </div>
        </div>
        <article
          v-for="message in messages"
          :key="message.id"
          class="max-w-[82%] rounded-xl border px-4 py-3 text-sm leading-relaxed"
          :class="
            message.role === 'user'
              ? 'ml-auto border-c-border-accent bg-c-accent-soft'
              : 'border-c-border bg-c-panel/55'
          "
        >
          <p class="mb-1 text-10px text-c-text-muted">
            {{ message.role === 'user' ? '演练输入' : '模型响应' }}
          </p>
          <p>{{ message.text }}</p>
          <p v-if="message.status === 'interrupted'" class="mt-2 text-10px text-c-warning">
            已中断
          </p>
          <p v-if="message.status === 'error'" class="mt-2 text-10px text-c-error">执行失败</p>
        </article>
      </div>

      <footer class="shrink-0 border-t border-c-border bg-c-surface/55 p-4">
        <textarea
          v-model="draft"
          rows="3"
          class="w-full resize-none rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-sm outline-none transition-colors duration-200 placeholder:text-c-text-muted focus:border-c-border-accent"
          placeholder="输入要验证的对话，内容不会自动发送"
          @keydown.ctrl.enter.prevent="runPrivateExercise"
        />
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <button
            class="btn-ghost"
            type="button"
            :aria-pressed="isRecording"
            @click="toggleRecording"
          >
            {{ isRecording ? '停止模拟录音' : '模拟语音录制' }}
          </button>
          <button
            v-if="isStreaming"
            class="btn-ghost text-c-warning"
            type="button"
            @click="stopStream('interrupted')"
          >
            中断生成
          </button>
          <button
            v-else
            class="btn-ghost"
            type="button"
            :disabled="!messages.length"
            @click="previewSpeech"
          >
            {{ isSpeaking ? '停止说话状态' : '模拟说话状态' }}
          </button>
          <span class="flex-1" />
          <button
            class="btn-accent"
            type="button"
            :disabled="!draft.trim() || isStreaming || isCheckingRuntime"
            @click="runPrivateExercise"
          >
            发送到私密模型
          </button>
        </div>
      </footer>
    </div>

    <aside class="glass min-h-0 overflow-y-auto px-5 py-4">
      <h2 class="text-sm font-semibold">执行证据</h2>
      <p class="mt-1 text-xs text-c-text-muted">用于确认演练没有进入公开链路</p>
      <dl v-if="evidence.length" class="mt-4 divide-y divide-c-border">
        <div
          v-for="item in evidence"
          :key="item.label"
          class="flex items-center justify-between gap-4 py-3 text-xs"
        >
          <dt class="text-c-text-muted">{{ item.label }}</dt>
          <dd class="font-mono text-c-text-secondary">{{ item.value }}</dd>
        </div>
      </dl>
      <div
        v-else
        class="mt-4 rounded-xl border border-c-border bg-c-panel/35 p-4 text-xs text-c-text-muted"
      >
        运行一次私密演练后，这里会记录模型身份与公开链路隔离状态。
      </div>
    </aside>
  </section>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

interface SandboxMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  status: 'complete' | 'streaming' | 'interrupted'
}

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const messages = ref<SandboxMessage[]>([])
const isRecording = ref(false)
const isStreaming = ref(false)
const isSpeaking = ref(false)
const evidence = ref<Array<{ label: string; value: string }>>([])
let sequence = 0
let streamTimer: ReturnType<typeof setInterval> | null = null

const draft = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

function stopStream(status: 'complete' | 'interrupted'): void {
  if (streamTimer) clearInterval(streamTimer)
  streamTimer = null
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
}

function runLocalExercise(): void {
  const text = draft.value.trim()
  if (!text || isStreaming.value) return

  const startedAt = performance.now()
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

  const localReply = '本地演练已记录。当前沙盒未连接模型，因此不会进入直播、字幕、语音或记忆链路。'
  let index = 0
  streamTimer = setInterval(() => {
    response.text += localReply[index] ?? ''
    index += 1
    if (index >= localReply.length) {
      stopStream('complete')
      evidence.value = [
        { label: '执行边界', value: '浏览器本地' },
        { label: '网络请求', value: '0' },
        { label: '公开输出', value: '未触发' },
        { label: '耗时', value: `${Math.round(performance.now() - startedAt)} ms` },
      ]
    }
  }, 20)
}

function toggleRecording(): void {
  isRecording.value = !isRecording.value
  if (!isRecording.value && !draft.value.trim()) draft.value = '模拟语音输入已停止，等待编辑确认。'
}

function previewSpeech(): void {
  if (!messages.value.length || isStreaming.value) return
  isSpeaking.value = !isSpeaking.value
}

onUnmounted(() => {
  if (streamTimer) clearInterval(streamTimer)
})
</script>

<template>
  <section class="grid h-full min-h-0 gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(300px,2fr)]">
    <div class="glass flex min-h-0 flex-col overflow-hidden">
      <header class="shrink-0 border-b border-c-border px-5 py-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 class="text-sm font-semibold">私密对话演练</h1>
            <p class="mt-1 text-xs text-c-text-muted">仅保存在当前浏览器，不调用 API 或 Socket</p>
          </div>
          <span
            class="rounded-lg border border-c-warning/40 bg-c-warning/10 px-2 py-1 text-10px text-c-warning"
          >
            本地模式
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
            {{ message.role === 'user' ? '演练输入' : '本地响应' }}
          </p>
          <p>{{ message.text }}</p>
          <p v-if="message.status === 'interrupted'" class="mt-2 text-10px text-c-warning">
            已中断
          </p>
        </article>
      </div>

      <footer class="shrink-0 border-t border-c-border bg-c-surface/55 p-4">
        <textarea
          v-model="draft"
          rows="3"
          class="w-full resize-none rounded-xl border border-c-border bg-c-panel/55 px-3 py-2 text-sm outline-none transition-colors duration-200 placeholder:text-c-text-muted focus:border-c-border-accent"
          placeholder="输入要验证的对话，内容不会自动发送"
          @keydown.ctrl.enter.prevent="runLocalExercise"
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
            :disabled="!draft.trim() || isStreaming"
            @click="runLocalExercise"
          >
            开始本地演练
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
        运行一次本地演练后，这里会记录执行边界、网络请求与公开输出状态。
      </div>
    </aside>
  </section>
</template>

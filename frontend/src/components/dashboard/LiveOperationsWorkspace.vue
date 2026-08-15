<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import InputBar from '@/components/chat/InputBar.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import ProgramRunPanel from '@/components/program/ProgramRunPanel.vue'
import PreflightDrawer from '@/components/dashboard/PreflightDrawer.vue'
import ToolApprovalQueue from '@/components/dashboard/ToolApprovalQueue.vue'
import { sendDeveloperChatText } from '@/composables/chatTransport'
import { useDanmaku } from '@/composables/useDanmaku'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import { useDanmakuStore } from '@/stores/danmaku'
import {
  useDashboardStore,
  type LiveActivity,
  type LiveContent,
  type LiveTurn,
} from '@/stores/dashboardStore'
import type { ChatMessage } from '@/types/chat'

const store = useDashboardStore()
const danmakuStore = useDanmakuStore()
useDanmaku()
const selectedTraceId = ref('')
const historyLocked = ref(false)
const feedMode = ref<'turns' | 'raw'>('turns')
const preflightOpen = ref(false)
const preflightButtonRef = ref<HTMLButtonElement | null>(null)
const pendingTurns = ref<Array<{ traceId: string; text: string; startedAt: number }>>([])
let summaryTimer: ReturnType<typeof setInterval> | null = null
let detailTimer: ReturnType<typeof setInterval> | null = null
let mounted = true

const selectedTurn = computed(
  () => store.liveTurns.find((turn) => turn.trace_id === selectedTraceId.value) ?? null,
)
const selectedDetail = computed(() => store.liveTurnDetails[selectedTraceId.value] ?? null)
const metrics = computed(
  () =>
    store.liveMetrics ?? {
      turn_count: 0,
      model_calls: 0,
      tool_calls: 0,
      tool_success_rate: 100,
      mc_command_count: 0,
      mc_status: 'idle',
    },
)
const metricItems = computed(() => [
  { label: '本场回合', value: String(metrics.value.turn_count) },
  { label: '模型调用', value: String(metrics.value.model_calls) },
  { label: '工具调用', value: String(metrics.value.tool_calls) },
  { label: '工具成功率', value: `${metrics.value.tool_success_rate}%` },
  { label: 'MC 指令', value: metrics.value.mc_status },
])
const rawMessages = computed(() => [...danmakuStore.messages].reverse())
const audienceCount = computed(
  () => new Set(danmakuStore.messages.map((message) => message.user_id)).size,
)

onMounted(async () => {
  await refreshSummary()
  // Guard against the component unmounting while awaits are in flight; the
  // timers and socket listener below must not register on a dead instance.
  if (!mounted) return
  followLatest()
  await refreshDetail()
  if (!mounted) return
  summaryTimer = setInterval(() => {
    if (!document.hidden) void refreshSummary()
  }, 2000)
  detailTimer = setInterval(() => {
    if (!document.hidden) void refreshDetail()
  }, 1000)
  getSocket()?.on(Events.MINECRAFT.COMMAND_TRANSITION, onMinecraftTransition)
})

onUnmounted(() => {
  mounted = false
  if (summaryTimer) clearInterval(summaryTimer)
  if (detailTimer) clearInterval(detailTimer)
  getSocket()?.off(Events.MINECRAFT.COMMAND_TRANSITION, onMinecraftTransition)
})

watch(
  () => store.liveTurns[0]?.trace_id,
  () => {
    reconcilePending()
    if (!historyLocked.value) followLatest()
  },
)

watch(selectedTraceId, () => void refreshDetail())

function onMinecraftTransition() {
  void refreshDetail()
  void refreshSummary()
}

async function refreshSummary() {
  await store.fetchLive(20)
}

async function refreshDetail() {
  if (selectedTurn.value) await store.fetchLiveTurn(selectedTurn.value.trace_id)
}

function followLatest() {
  historyLocked.value = false
  selectedTraceId.value = store.liveTurns[0]?.trace_id ?? ''
}

function selectTurn(traceId: string) {
  selectedTraceId.value = traceId
  historyLocked.value = traceId !== store.liveTurns[0]?.trace_id
}

function sendDeveloperText(text: string) {
  const socket = getSocket()
  if (!socket) return
  const command = sendDeveloperChatText(socket, text)
  pendingTurns.value.unshift({
    traceId: command.task_id,
    text,
    startedAt: Date.now() / 1000,
  })
  if (!historyLocked.value) selectedTraceId.value = command.task_id
  void refreshSummary()
}

function reconcilePending() {
  const committed = new Set(store.liveTurns.map((turn) => turn.trace_id))
  pendingTurns.value = pendingTurns.value.filter((turn) => !committed.has(turn.traceId))
}

function contentText(content: LiveContent, fallback: string) {
  if (content.text) return content.text
  if (content.digest)
    return `已脱敏 · ${content.character_count ?? 0} 字 · ${content.digest.slice(0, 10)}…`
  return fallback
}

function sourceLabel(turn: LiveTurn) {
  return turn.actor_role === 'developer' ? '开发者' : '弹幕'
}

function turnMessage(turn: LiveTurn, role: 'user' | 'assistant'): ChatMessage {
  const content = role === 'user' ? turn.content.user : turn.content.assistant
  return {
    id: `${turn.trace_id}:${role}`,
    role,
    text: contentText(content, role === 'user' ? '输入已接收' : '模型正在组织公开回答…'),
    timestamp: turn.started_at * 1000,
    status: role === 'assistant' && !turn.finished_at ? 'streaming' : 'complete',
    source: 'text',
    message_id: turn.message_id,
    conversation_id: turn.conversation_id,
    task_id: turn.trace_id,
    turn_id: turn.trace_id,
  }
}

function pendingMessage(pending: {
  traceId: string
  text: string
  startedAt: number
}): ChatMessage {
  return {
    id: pending.traceId,
    role: 'user',
    text: pending.text,
    timestamp: pending.startedAt * 1000,
    status: 'complete',
    source: 'text',
    task_id: pending.traceId,
    turn_id: pending.traceId,
  }
}

function formatTime(value?: number | null) {
  if (!value) return '--:--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value * 1000))
}

function formatDuration(value?: number | null) {
  if (value == null) return '运行中'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

function activityTone(activity: LiveActivity) {
  if (activity.status === 'success') return 'border-c-success text-c-success'
  if (activity.status === 'error' || activity.status === 'cancelled') {
    return 'border-c-error text-c-error'
  }
  return 'border-c-warning text-c-warning'
}

function activityDotTone(activity: LiveActivity) {
  if (activity.status === 'success') return 'bg-c-success'
  if (activity.status === 'error' || activity.status === 'cancelled') return 'bg-c-error'
  return 'bg-c-warning'
}

function rawValue(activity: LiveActivity, key: string) {
  const value = activity.attributes[key]
  return typeof value === 'string' && value ? value : null
}

function closePreflight(): void {
  preflightOpen.value = false
  requestAnimationFrame(() => preflightButtonRef.value?.focus())
}
</script>

<template>
  <main
    class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 sm:p-4 lg:overflow-hidden"
    data-testid="live-operations-workspace"
  >
    <header class="flex shrink-0 flex-wrap items-center justify-between gap-3 px-1">
      <div class="min-w-52">
        <div class="flex items-center gap-2">
          <span class="h-2 w-2 rounded-full bg-c-success shadow-[0_0_8px_var(--c-success)]" />
          <h1 class="text-base font-semibold">直播执行</h1>
        </div>
        <p class="mt-1 text-xs text-c-text-muted">
          开发者输入仅在后台可见，公开回答自动进入直播链路
        </p>
      </div>

      <dl class="flex min-w-0 flex-1 items-center justify-end overflow-x-auto">
        <div
          v-for="item in metricItems"
          :key="item.label"
          class="min-w-24 border-l border-c-border px-4 first:border-l-0"
        >
          <dt class="whitespace-nowrap text-10px text-c-text-muted">{{ item.label }}</dt>
          <dd class="mt-0.5 whitespace-nowrap font-mono text-sm font-semibold uppercase">
            {{ item.value }}
          </dd>
        </div>
      </dl>
      <button
        ref="preflightButtonRef"
        class="btn-accent shrink-0"
        type="button"
        aria-haspopup="dialog"
        @click="preflightOpen = true"
      >
        开播准备
      </button>
    </header>

    <ProgramRunPanel />
    <ToolApprovalQueue />

    <div class="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(340px,2fr)]">
      <section class="glass flex min-h-136 flex-col overflow-hidden lg:min-h-0">
        <div
          class="flex shrink-0 items-start justify-between gap-4 border-b border-c-border px-5 py-4"
        >
          <div>
            <h2 class="text-sm font-semibold">
              {{ feedMode === 'turns' ? '执行回合' : '原始弹幕' }}
            </h2>
            <p class="mt-1 text-xs text-c-text-muted">
              {{
                feedMode === 'turns'
                  ? '统一显示后台输入、弹幕回合与公开回答'
                  : '按接收顺序查看未经执行编排的观众输入'
              }}
            </p>
          </div>
          <div class="flex gap-1" role="group" aria-label="现场消息视图">
            <button
              class="rounded-lg px-2.5 py-1 text-10px transition-colors duration-200"
              :class="
                feedMode === 'turns'
                  ? 'bg-c-accent-soft text-c-accent'
                  : 'bg-c-panel/50 text-c-text-dim hover:bg-c-panel/80 hover:text-c-accent'
              "
              type="button"
              :aria-pressed="feedMode === 'turns'"
              @click="feedMode = 'turns'"
            >
              执行回合
            </button>
            <button
              class="rounded-lg px-2.5 py-1 text-10px transition-colors duration-200"
              :class="
                feedMode === 'raw'
                  ? 'bg-c-accent-soft text-c-accent'
                  : 'bg-c-panel/50 text-c-text-dim hover:bg-c-panel/80 hover:text-c-accent'
              "
              type="button"
              :aria-pressed="feedMode === 'raw'"
              @click="feedMode = 'raw'"
            >
              原始弹幕
            </button>
          </div>
        </div>

        <div
          v-if="feedMode === 'turns'"
          class="ops-scroll min-h-0 flex-1 overflow-y-auto"
          data-testid="live-turn-list"
        >
          <button
            v-for="pending in pendingTurns"
            :key="pending.traceId"
            class="w-full border-l-2 border-c-accent border-b border-c-border bg-c-panel/35 px-5 py-4 text-left"
            :aria-label="`查看投递中的开发者回合 ${pending.traceId}`"
            @click="selectTurn(pending.traceId)"
          >
            <div class="mb-3 flex items-center justify-between gap-3">
              <span class="text-xs font-medium text-c-accent">开发者 · 投递中</span>
              <span class="font-mono text-10px text-c-text-muted">{{
                formatTime(pending.startedAt)
              }}</span>
            </div>
            <div class="flex flex-col">
              <MessageBubble :message="pendingMessage(pending)" />
            </div>
          </button>

          <button
            v-for="turn in store.liveTurns"
            :key="turn.trace_id"
            class="w-full border-l-2 border-b border-c-border px-5 py-4 text-left transition-colors duration-200"
            :class="
              turn.trace_id === selectedTraceId
                ? 'border-l-c-accent bg-c-panel/45'
                : 'border-l-transparent hover:bg-c-panel/25'
            "
            :data-trace-id="turn.trace_id"
            :aria-pressed="turn.trace_id === selectedTraceId"
            @click="selectTurn(turn.trace_id)"
          >
            <div class="mb-3 flex items-center justify-between gap-3">
              <div class="flex min-w-0 items-center gap-2">
                <span
                  class="rounded-lg px-2 py-1 text-10px font-medium"
                  :class="
                    turn.actor_role === 'developer'
                      ? 'bg-c-accent-soft text-c-accent'
                      : 'bg-c-blue/10 text-c-blue'
                  "
                >
                  {{ sourceLabel(turn) }}
                </span>
                <span class="truncate font-mono text-10px text-c-text-muted">
                  {{ turn.trace_id.slice(0, 8) }}
                </span>
              </div>
              <span class="whitespace-nowrap font-mono text-10px text-c-text-muted">
                {{ formatTime(turn.started_at) }} · {{ formatDuration(turn.duration_ms) }}
              </span>
            </div>
            <div class="flex flex-col">
              <MessageBubble :message="turnMessage(turn, 'user')" />
              <MessageBubble :message="turnMessage(turn, 'assistant')" />
            </div>
          </button>

          <div
            v-if="!pendingTurns.length && !store.liveTurns.length"
            class="grid min-h-72 place-items-center px-6 text-center"
          >
            <div>
              <p class="text-sm text-c-text-secondary">还没有直播回合</p>
              <p class="mt-1 text-xs text-c-text-muted">从下方输入一个话题，或等待下一条弹幕</p>
            </div>
          </div>
        </div>

        <div
          v-else
          class="ops-scroll min-h-0 flex-1 overflow-y-auto"
          data-testid="raw-danmaku-list"
        >
          <div
            class="grid grid-cols-3 border-b border-c-border bg-c-panel/35 px-5 py-3 text-10px text-c-text-muted"
          >
            <span>连接 {{ danmakuStore.connected ? '直播中' : danmakuStore.state }}</span>
            <span class="text-center">观众 {{ audienceCount }}</span>
            <span class="text-right">累计 {{ danmakuStore.messageCount }}</span>
          </div>
          <article
            v-for="message in rawMessages"
            :key="`${message.user_id}:${message.timestamp}:${message.text}`"
            class="border-b border-c-border px-5 py-3"
          >
            <div class="flex items-center justify-between gap-3 text-10px text-c-text-muted">
              <span class="truncate">{{ message.user_name }} · {{ message.user_id }}</span>
              <span class="shrink-0 font-mono">{{ formatTime(message.timestamp) }}</span>
            </div>
            <p class="mt-2 break-words text-sm text-c-text-secondary">{{ message.text }}</p>
          </article>
          <div v-if="!rawMessages.length" class="grid min-h-72 place-items-center px-6 text-center">
            <div>
              <p class="text-sm text-c-text-secondary">还没有收到原始弹幕</p>
              <p class="mt-1 text-xs text-c-text-muted">
                连接 Bilibili 房间后，观众输入会先出现在这里
              </p>
            </div>
          </div>
        </div>

        <div
          v-if="feedMode === 'turns'"
          class="shrink-0 border-t border-c-border bg-c-surface/55 px-4 pb-4 pt-3"
        >
          <p class="mb-2 px-1 text-10px text-c-text-muted">
            输入不会进入字幕或语音，AI 的公开回答会自动播出
          </p>
          <InputBar
            appearance="surface"
            :send-text="sendDeveloperText"
            :show-voice="false"
            placeholder="从后台向直播中的 AI 提出话题…"
          />
        </div>
      </section>

      <div class="flex min-h-136 flex-col gap-3 lg:min-h-0">
        <aside class="glass flex min-h-96 flex-1 flex-col overflow-hidden lg:min-h-0">
          <div class="shrink-0 border-b border-c-border px-5 py-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <h2 class="text-sm font-semibold">执行检查器</h2>
                <p class="mt-1 truncate font-mono text-10px text-c-text-muted">
                  {{
                    selectedTurn
                      ? `${sourceLabel(selectedTurn)} · ${selectedTurn.trace_id}`
                      : '选择一个回合查看执行阶段'
                  }}
                </p>
              </div>
              <button
                class="shrink-0 rounded-lg px-2.5 py-1.5 text-10px transition-colors duration-200"
                :class="
                  historyLocked
                    ? 'bg-c-accent-soft text-c-accent hover:bg-c-accent/25'
                    : 'bg-c-panel/50 text-c-text-dim hover:bg-c-panel/80 hover:text-c-accent'
                "
                data-testid="follow-latest"
                @click="followLatest"
              >
                {{ historyLocked ? '回到最新' : '跟随最新' }}
              </button>
            </div>

            <div
              v-if="selectedTurn"
              class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-10px"
            >
              <span class="text-c-text-muted">
                来源
                <strong class="font-medium text-c-text-secondary">{{
                  sourceLabel(selectedTurn)
                }}</strong>
              </span>
              <span class="text-c-text-muted">
                总耗时
                <strong class="font-mono font-medium text-c-text-secondary">{{
                  formatDuration(selectedTurn.duration_ms)
                }}</strong>
              </span>
              <span class="text-c-text-muted">
                内容
                <strong class="font-mono font-medium uppercase text-c-text-secondary">{{
                  selectedTurn.privacy_mode === 'full' ? '后台原文' : '历史脱敏'
                }}</strong>
              </span>
            </div>
          </div>

          <ol
            class="ops-scroll min-h-0 flex-1 overflow-y-auto px-5 py-4"
            data-testid="execution-timeline"
          >
            <li
              v-for="(activity, index) in selectedDetail?.activities ?? []"
              :key="activity.id"
              class="grid grid-cols-[12px_minmax(0,1fr)] gap-3"
            >
              <div class="flex flex-col items-center">
                <span
                  class="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                  :class="activityDotTone(activity)"
                />
                <span
                  v-if="index < (selectedDetail?.activities.length ?? 0) - 1"
                  class="my-1 w-px flex-1 bg-c-border"
                />
              </div>

              <article class="min-w-0 pb-5">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <p class="text-sm font-medium">{{ activity.label }}</p>
                    <p class="mt-1 truncate font-mono text-10px text-c-text-muted">
                      {{ activity.name }} · {{ activity.layer }}
                    </p>
                  </div>
                  <span
                    class="shrink-0 rounded-lg border px-2 py-1 font-mono text-9px uppercase"
                    :class="activityTone(activity)"
                  >
                    {{ activity.status }}
                  </span>
                </div>

                <div
                  class="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-10px text-c-text-secondary"
                >
                  <span>{{ formatDuration(activity.duration_ms) }}</span>
                  <span v-if="activity.provider">{{ activity.provider }}</span>
                  <span v-if="activity.model">{{ activity.model }}</span>
                  <span v-if="activity.attributes.tool_source"
                    >来源 {{ activity.attributes.tool_source }}</span
                  >
                  <span v-if="activity.attributes.mcp_server"
                    >MCP {{ activity.attributes.mcp_server }}</span
                  >
                </div>

                <p v-if="activity.error" class="mt-2 text-xs text-c-error">
                  {{ activity.error }}
                </p>

                <div
                  v-if="activity.minecraft"
                  class="mt-3 border-l-2 border-c-blue bg-c-panel/35 px-3 py-2.5 text-xs"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-c-text-muted">MC 指令</span>
                    <strong class="font-mono uppercase text-c-text">{{
                      activity.minecraft.state
                    }}</strong>
                  </div>
                  <p
                    v-if="selectedTurn?.privacy_mode === 'full'"
                    class="mt-2 break-all font-mono text-10px text-c-text-secondary"
                  >
                    {{ activity.minecraft.command_id }}
                  </p>
                  <p v-if="activity.minecraft.failure_reason" class="mt-2 text-c-error">
                    {{ activity.minecraft.failure_reason }}
                  </p>
                  <ol class="mt-2 space-y-1 font-mono text-10px text-c-text-secondary">
                    <li
                      v-for="(transition, transitionIndex) in activity.minecraft.transitions"
                      :key="transitionIndex"
                    >
                      {{ transition.from_state ?? 'accepted' }} → {{ transition.to_state }} ·
                      {{ transition.reason_code }}
                    </li>
                  </ol>
                </div>

                <details
                  v-if="
                    selectedTurn?.privacy_mode === 'full' &&
                    (rawValue(activity, 'arguments_text') || rawValue(activity, 'result_text'))
                  "
                  open
                  class="mt-3"
                >
                  <summary class="cursor-pointer text-xs text-c-accent">工具原始数据</summary>
                  <pre
                    v-if="rawValue(activity, 'arguments_text')"
                    class="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-c-panel/50 p-3 font-mono text-10px"
                    >{{ rawValue(activity, 'arguments_text') }}</pre>
                  <pre
                    v-if="rawValue(activity, 'result_text')"
                    class="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-c-panel/50 p-3 font-mono text-10px"
                    >{{ rawValue(activity, 'result_text') }}</pre>
                </details>
                <p
                  v-else-if="
                    activity.attributes.arguments_digest || activity.attributes.result_digest
                  "
                  class="mt-2 text-10px text-c-text-muted"
                >
                  原始数据已脱敏，仅保留长度与摘要
                </p>
              </article>
            </li>

            <li
              v-if="!selectedDetail?.activities?.length"
              class="grid min-h-72 place-items-center text-center"
            >
              <div>
                <p class="text-sm text-c-text-secondary">
                  {{ selectedTraceId ? '正在等待执行阶段' : '尚未选择回合' }}
                </p>
                <p class="mt-1 text-xs text-c-text-muted">
                  {{
                    selectedTraceId
                      ? '模型、工具和 MC 状态会在这里实时更新'
                      : '从左侧消息流选择一个回合'
                  }}
                </p>
              </div>
            </li>
          </ol>
        </aside>
      </div>
    </div>

    <p
      v-if="store.error"
      class="shrink-0 rounded-lg border border-c-error/40 bg-c-error/10 px-3 py-2 text-xs text-c-error"
      role="alert"
    >
      {{ store.error }}
    </p>
    <PreflightDrawer :open="preflightOpen" @close="closePreflight" />
  </main>
</template>

<style scoped>
.ops-scroll {
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: var(--c-border) transparent;
}

.ops-scroll::-webkit-scrollbar {
  width: 4px;
}

.ops-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.ops-scroll::-webkit-scrollbar-thumb {
  border-radius: var(--r-full);
  background: var(--c-border);
}
</style>

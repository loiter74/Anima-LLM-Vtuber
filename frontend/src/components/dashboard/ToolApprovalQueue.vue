<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

type ApprovalTool = {
  tool_call_id: string
  name: string
  arguments: Record<string, unknown>
}

type Approval = {
  approval_id: string
  task_id?: string | null
  expires_at: number
  tools: ApprovalTool[]
  status: string
}

const approvals = ref<Approval[]>([])
const deciding = ref<string | null>(null)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null

const ordered = computed(() =>
  [...approvals.value].sort((left, right) => left.expires_at - right.expires_at),
)

onMounted(() => {
  const socket = getSocket()
  socket?.on(Events.TOOL.APPROVAL_REQUIRED, upsert)
  socket?.on(Events.TOOL.APPROVAL_RESOLVED, removeResolved)
  socket?.on('connect', refresh)
  refresh()
  timer = setInterval(() => (now.value = Date.now()), 1000)
})

onUnmounted(() => {
  const socket = getSocket()
  socket?.off(Events.TOOL.APPROVAL_REQUIRED, upsert)
  socket?.off(Events.TOOL.APPROVAL_RESOLVED, removeResolved)
  socket?.off('connect', refresh)
  if (timer) clearInterval(timer)
})

function refresh(): void {
  getSocket()?.emit(
    Events.TOOL.APPROVAL_LIST,
    {},
    (response: { ok: boolean; approvals?: Approval[] }) => {
      if (response.ok) approvals.value = response.approvals ?? []
    },
  )
}

function upsert(approval: Approval): void {
  approvals.value = [
    approval,
    ...approvals.value.filter((item) => item.approval_id !== approval.approval_id),
  ]
}

function removeResolved(payload: { approval_id: string }): void {
  approvals.value = approvals.value.filter((item) => item.approval_id !== payload.approval_id)
}

function remaining(approval: Approval): number {
  return Math.max(0, Math.ceil((approval.expires_at * 1000 - now.value) / 1000))
}

function decide(approval: Approval, decision: 'approve' | 'reject'): void {
  deciding.value = approval.approval_id
  getSocket()?.emit(
    Events.TOOL.APPROVAL_DECIDE,
    { approval_id: approval.approval_id, decision },
    () => {
      deciding.value = null
      refresh()
    },
  )
}
</script>

<template>
  <section
    v-if="ordered.length"
    class="glass shrink-0 rounded-xl border border-c-warning/40 p-4"
    data-testid="tool-approval-queue"
  >
    <header class="flex items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-c-warning">待审批工具</h2>
        <p class="mt-1 text-xs text-c-text-muted">Minecraft 变更操作将在 120 秒后自动拒绝</p>
      </div>
      <span class="rounded-xl bg-c-warning/15 px-2 py-1 font-mono text-xs text-c-warning">
        {{ ordered.length }}
      </span>
    </header>
    <article
      v-for="approval in ordered"
      :key="approval.approval_id"
      class="mt-3 rounded-xl bg-c-panel/70 p-3"
    >
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-sm font-medium">
            {{ approval.tools.map((tool) => tool.name).join(' · ') }}
          </p>
          <p class="mt-1 font-mono text-10px text-c-text-muted">
            {{ approval.task_id || approval.approval_id }} · {{ remaining(approval) }}s
          </p>
        </div>
        <div class="flex gap-2">
          <button
            class="btn-secondary"
            type="button"
            :disabled="deciding === approval.approval_id"
            @click="decide(approval, 'reject')"
          >
            拒绝
          </button>
          <button
            class="btn-accent"
            type="button"
            :disabled="deciding === approval.approval_id || remaining(approval) === 0"
            @click="decide(approval, 'approve')"
          >
            批准并继续
          </button>
        </div>
      </div>
      <pre
        class="mt-3 max-h-32 overflow-auto rounded-xl bg-c-bg/50 p-3 text-10px text-c-text-dim"
        >{{ JSON.stringify(approval.tools, null, 2) }}</pre>
    </article>
  </section>
</template>

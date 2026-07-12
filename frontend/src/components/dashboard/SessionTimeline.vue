<script setup lang="ts">
import { useDashboardStore } from '../../stores/dashboardStore'

const store = useDashboardStore()

function formatDuration(ms: number | null): string {
  if (ms === null) return 'running'
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function statusClass(status: string | null): string {
  if (status === 'success') return 'text-c-success'
  if (status === 'degraded') return 'text-c-warning'
  if (status === null) return 'text-c-text-muted'
  return 'text-c-error'
}
</script>

<template>
  <div class="bg-c-card/50 rounded-xl p-4 border border-c-border">
    <h3 class="text-sm font-medium text-c-text-dim mb-4">Recent Sessions</h3>
    <div class="space-y-1 max-h-80 overflow-y-auto scrollbar-thin">
      <div
        v-for="trace in store.traces.slice(0, 30)"
        :key="trace.trace_id"
        class="flex items-center justify-between p-2 rounded-lg hover:bg-white/5 transition-colors cursor-default"
      >
        <div class="flex items-center gap-3 min-w-0">
          <span class="text-lg shrink-0">{{ trace.input_type === 'audio' ? '🎤' : '💬' }}</span>
          <div class="min-w-0">
            <div class="text-sm text-c-text truncate max-w-48">
              {{ trace.runtime_profile }} · {{ trace.trace_id }}
            </div>
            <div class="text-xs text-c-text-muted">
              {{ new Date(trace.started_at * 1000).toLocaleString() }}
            </div>
          </div>
        </div>
        <div class="text-right shrink-0 ml-3">
          <div class="text-sm text-c-text-dim">{{ formatDuration(trace.duration_ms) }}</div>
          <div :class="statusClass(trace.outcome)" class="text-xs">
            {{ trace.outcome ?? 'running' }}
          </div>
        </div>
      </div>
      <div v-if="!store.traces.length" class="text-c-text-muted text-center py-8 text-sm">
        No sessions yet
      </div>
    </div>
  </div>
</template>

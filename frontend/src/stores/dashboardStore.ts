import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface StatsOverview {
  total_requests: number
  success_rate: number
  avg_duration_ms: number
  p95_duration_ms: number
}

export interface NodeStats {
  node_name: string
  call_count: number
  avg_duration_ms: number
  error_count: number
  error_rate: number
}

export interface Trace {
  trace_id: string
  session_id: string
  input_type: string
  user_text: string
  total_duration_ms: number
  status: string
  error_msg?: string | null
  created_at: string
}

export interface TraceSpan {
  span_id: string
  parent_span_id: string | null
  node_name: string
  duration_ms: number | null
  status: string
  input_summary: string | null
  output_summary: string | null
  attributes: string | null
  events: string | null
  kind?: number | null
  created_at: string
}

export interface ConversationTurn {
  trace_id: string
  session_id: string
  input_type: string
  user_text: string
  assistant_text: string
  status: string
  error_msg: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface TraceDetail extends Trace {
  error_msg: string | null
  spans: TraceSpan[]
  conversation_turn?: ConversationTurn | null
  tree?: unknown[]
}

export const useDashboardStore = defineStore('dashboard', () => {
  const overview = ref<StatsOverview | null>(null)
  const nodeStats = ref<NodeStats[]>([])
  const traces = ref<Trace[]>([])
  const traceDetails = ref<Record<string, TraceDetail>>({})
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref<string | null>(null)

  const avgLatency = computed(() => overview.value?.avg_duration_ms ?? 0)
  const totalSessions = computed(() => overview.value?.total_requests ?? 0)
  const errorRate = computed(() => {
    if (!overview.value || !overview.value.success_rate) return 0
    return Math.round((100 - overview.value.success_rate) * 10) / 10
  })

  async function fetchOverview() {
    try {
      const res = await fetch('/api/stats/overview')
      overview.value = await res.json()
    } catch (e) {
      error.value = String(e)
    }
  }

  async function fetchNodeStats() {
    try {
      const res = await fetch('/api/stats/nodes')
      nodeStats.value = await res.json()
    } catch (e) {
      error.value = String(e)
    }
  }

  async function fetchTraces(limit = 50, offset = 0) {
    try {
      const res = await fetch(`/api/stats/traces?limit=${limit}&offset=${offset}`)
      traces.value = await res.json()
    } catch (e) {
      error.value = String(e)
    }
  }

  async function fetchTraceDetail(traceId: string): Promise<TraceDetail | null> {
    if (traceDetails.value[traceId]) {
      return traceDetails.value[traceId]
    }

    detailLoading.value = true
    try {
      const res = await fetch(`/api/stats/traces/${traceId}/tree`)
      const detail = await res.json()
      if (detail.error) {
        error.value = detail.error
        return null
      }

      traceDetails.value = {
        ...traceDetails.value,
        [traceId]: {
          ...detail,
          spans: detail.spans ?? [],
        },
      }
      return traceDetails.value[traceId]
    } catch (e) {
      error.value = String(e)
      return null
    } finally {
      detailLoading.value = false
    }
  }

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      await Promise.all([fetchOverview(), fetchNodeStats(), fetchTraces()])
    } finally {
      loading.value = false
    }
  }

  return {
    overview, nodeStats, traces, traceDetails, loading, detailLoading, error,
    avgLatency, totalSessions, errorRate,
    fetchAll, fetchOverview, fetchNodeStats, fetchTraces, fetchTraceDetail,
  }
})

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type TraceOutcome = 'success' | 'degraded' | 'failed' | 'cancelled' | 'aborted' | null
export type OperationStatus = 'success' | 'skipped' | 'degraded' | 'error' | 'cancelled' | null

export interface StatsOverview {
  api_version: '2'
  total_requests: number
  success_count: number
  degraded_count: number
  failed_count: number
  success_rate: number
  avg_duration_ms: number
}

export interface NodeStats {
  api_version: '2'
  layer: string
  name: string
  provider: string | null
  model: string | null
  operation_count: number
  success_count: number
  degraded_count: number
  failure_count: number
  avg_duration_ms: number | null
}

export interface Trace {
  api_version: '2'
  trace_id: string
  message_id: string
  conversation_id: string
  session_id: string
  runtime_profile: string
  input_type: string
  privacy_mode: 'full' | 'redacted'
  started_at: number
  finished_at: number | null
  duration_ms: number | null
  outcome: TraceOutcome
  error_type: string | null
}

export interface TraceContent {
  text: string | null
  character_count: number | null
  byte_count: number | null
  digest: string | null
}

export interface TraceOperation {
  operation_id: string
  trace_id: string
  parent_operation_id: string | null
  layer: 'transport' | 'workflow' | 'service' | 'memory' | 'delivery'
  name: string
  critical_path: boolean
  started_at: number
  finished_at: number | null
  duration_ms: number | null
  status: OperationStatus
  provider: string | null
  model: string | null
  error_type: string | null
  error_summary: string | null
  attributes: Record<string, unknown>
  children: TraceOperation[]
}

export interface TraceEvent {
  event_id: string
  trace_id: string
  operation_id: string | null
  direction: 'ingress' | 'egress' | 'internal'
  name: string
  phase: string
  occurred_at: number
  payload_size: number
  identity_valid: boolean
  attributes: Record<string, unknown>
}

export interface PostTurnWork {
  pending: number
  completed: number
  failed: number
  operations: TraceOperation[]
}

export interface TraceDetail extends Trace {
  error_summary: string | null
  content: { user: TraceContent; assistant: TraceContent }
  attributes: Record<string, unknown>
  operations: TraceOperation[]
  operation_tree: TraceOperation[]
  events: TraceEvent[]
  post_turn: PostTurnWork
  schema_version: number
}

export interface LiveContent {
  text: string | null
  character_count: number | null
  byte_count: number | null
  digest: string | null
}

export interface LiveTurn {
  trace_id: string
  message_id: string
  conversation_id: string
  actor_role: 'developer' | 'viewer'
  source: string
  live_session_id: string | null
  audience: string | null
  started_at: number
  finished_at: number | null
  duration_ms: number | null
  outcome: TraceOutcome
  privacy_mode: 'full' | 'redacted'
  content: { user: LiveContent; assistant: LiveContent }
  tool_calls: number
  mc_status: string
}

export interface LiveMetrics {
  turn_count: number
  model_calls: number
  tool_calls: number
  tool_success_rate: number
  mc_command_count: number
  mc_status: string
}

export interface LiveActivity {
  id: string
  kind: 'model' | 'tool' | 'delivery' | 'stage'
  label: string
  name: string
  layer: string
  status: string
  started_at: number
  duration_ms: number | null
  provider: string | null
  model: string | null
  error: string | null
  attributes: Record<string, unknown>
  minecraft?: {
    command_id: string
    state: string
    failure_reason: string | null
    transitions: Array<Record<string, unknown>>
  } | null
}

export interface LiveTurnDetail extends Omit<
  LiveTurn,
  'actor_role' | 'source' | 'tool_calls' | 'mc_status'
> {
  activities: LiveActivity[]
  events: TraceEvent[]
}

export const useDashboardStore = defineStore('dashboard', () => {
  const overview = ref<StatsOverview | null>(null)
  const nodeStats = ref<NodeStats[]>([])
  const traces = ref<Trace[]>([])
  const traceDetails = ref<Record<string, TraceDetail>>({})
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref<string | null>(null)
  const liveMetrics = ref<LiveMetrics | null>(null)
  const liveTurns = ref<LiveTurn[]>([])
  const liveTurnDetails = ref<Record<string, LiveTurnDetail>>({})

  const avgLatency = computed(() => overview.value?.avg_duration_ms ?? 0)
  const totalSessions = computed(() => overview.value?.total_requests ?? 0)
  const errorRate = computed(() => {
    if (!overview.value) return 0
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
    if (traceDetails.value[traceId]) return traceDetails.value[traceId]

    detailLoading.value = true
    try {
      const res = await fetch(`/api/stats/traces/${traceId}/tree`)
      const detail = await res.json()
      if (detail.error) {
        error.value = detail.error
        return null
      }
      traceDetails.value = { ...traceDetails.value, [traceId]: detail }
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

  async function fetchLive(limit = 20) {
    try {
      const res = await fetch(`/api/stats/live?limit=${limit}`)
      const data = await res.json()
      if (!res.ok || data.error) throw new Error(data.error ?? `HTTP ${res.status}`)
      liveMetrics.value = data.metrics
      liveTurns.value = data.turns
    } catch (e) {
      error.value = String(e)
    }
  }

  async function fetchLiveTurn(traceId: string): Promise<LiveTurnDetail | null> {
    try {
      const res = await fetch(`/api/stats/live/turns/${encodeURIComponent(traceId)}`)
      const detail = await res.json()
      if (!res.ok || detail.error) throw new Error(detail.error ?? `HTTP ${res.status}`)
      liveTurnDetails.value = { ...liveTurnDetails.value, [traceId]: detail }
      error.value = null
      return detail
    } catch (e) {
      error.value = String(e)
      return null
    }
  }

  return {
    overview,
    nodeStats,
    traces,
    traceDetails,
    loading,
    detailLoading,
    error,
    avgLatency,
    totalSessions,
    errorRate,
    liveMetrics,
    liveTurns,
    liveTurnDetails,
    fetchAll,
    fetchOverview,
    fetchNodeStats,
    fetchTraces,
    fetchTraceDetail,
    fetchLive,
    fetchLiveTurn,
  }
})

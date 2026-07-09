<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  useDashboardStore,
  type Trace,
  type TraceDetail,
  type TraceSpan,
} from '../stores/dashboardStore'

type TraceNodeStatus = 'success' | 'warning' | 'error' | 'skipped'

interface TraceNodeDetail {
  id: string
  label: string
  role: string
  status: TraceNodeStatus
  durationMs: number
  input: string
  output: string
  attributes: Array<{ label: string; value: string }>
  events: string[]
}

const store = useDashboardStore()

const selectedTraceIndex = ref(0)
const selectedNodeId = ref('llm')
const userSelectedNode = ref(false)
const historyOpen = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const topology = [
  { id: 'input', label: 'Input', role: '用户输入' },
  { id: 'memory', label: 'Memory', role: '记忆检索' },
  { id: 'tools', label: 'Tools', role: '工具调用' },
  { id: 'llm', label: 'LLM', role: '推理生成' },
  { id: 'tts', label: 'TTS', role: '语音合成' },
  { id: 'output', label: 'Output', role: '响应出口' },
] as const

const selectedTrace = computed(() => store.traces[selectedTraceIndex.value] ?? null)
const selectedTraceDetail = computed(() => {
  const traceId = selectedTrace.value?.trace_id
  return traceId ? store.traceDetails[traceId] ?? null : null
})
const traceNodes = computed(() => buildNodeDetails(selectedTrace.value, selectedTraceDetail.value))
const selectedNode = computed(() =>
  traceNodes.value.find(node => node.id === selectedNodeId.value) ?? traceNodes.value[0] ?? null
)
const canGoNewer = computed(() => selectedTraceIndex.value > 0)
const canGoOlder = computed(() => selectedTraceIndex.value < store.traces.length - 1)
const healthTone = computed(() => {
  if (!selectedTrace.value) return 'idle'
  if (selectedTrace.value.status === 'error') return 'error'
  if (selectedTrace.value.status === 'success') return 'success'
  return 'warning'
})
const executedNodeCount = computed(() =>
  traceNodes.value.filter(node => node.status !== 'skipped').length
)
const failedNode = computed(() => traceNodes.value.find(node => node.status === 'error') ?? null)
const selectedTraceTime = computed(() => formatTime(selectedTrace.value?.created_at))

onMounted(async () => {
  await store.fetchAll()
  clampSelectedTrace()
  await loadSelectedTraceDetail()
  selectPreferredNode()
  refreshTimer = setInterval(() => store.fetchAll(), 10000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})

watch(() => store.traces.length, clampSelectedTrace)
watch(() => selectedTrace.value?.trace_id, () => {
  userSelectedNode.value = false
  void loadSelectedTraceDetail()
})
watch(() => selectedTraceDetail.value?.trace_id, (traceId) => {
  if (traceId && traceId === selectedTrace.value?.trace_id) {
    selectPreferredNode()
  }
})

function clampSelectedTrace() {
  if (!store.traces.length) {
    selectedTraceIndex.value = 0
    return
  }
  selectedTraceIndex.value = Math.min(selectedTraceIndex.value, store.traces.length - 1)
}

function selectPreferredNode() {
  if (userSelectedNode.value) return
  const errorNode = traceNodes.value.find(node => node.status === 'error')
  const activeLlmNode = traceNodes.value.find(node => node.id === 'llm' && node.status !== 'skipped')
  const firstCapturedNode = traceNodes.value.find(node => node.status !== 'skipped')
  selectedNodeId.value = errorNode?.id ?? activeLlmNode?.id ?? firstCapturedNode?.id ?? 'input'
}

function goNewer() {
  if (canGoNewer.value) selectedTraceIndex.value -= 1
}

function goOlder() {
  if (canGoOlder.value) selectedTraceIndex.value += 1
}

function goLatest() {
  selectedTraceIndex.value = 0
}

function selectTrace(index: number) {
  selectedTraceIndex.value = index
  historyOpen.value = false
}

function selectNode(nodeId: string) {
  userSelectedNode.value = true
  selectedNodeId.value = nodeId
}

async function loadSelectedTraceDetail() {
  const traceId = selectedTrace.value?.trace_id
  if (!traceId) return
  await store.fetchTraceDetail(traceId)
  if (selectedTrace.value?.trace_id === traceId) {
    await nextTick()
    selectPreferredNode()
  }
}

function buildNodeDetails(trace: Trace | null, detail: TraceDetail | null): TraceNodeDetail[] {
  const totalDuration = trace?.total_duration_ms ?? store.overview?.avg_duration_ms ?? 0
  const llmStats = store.nodeStats.find(node => node.node_name.toLowerCase().includes('llm'))
  const ttsStats = store.nodeStats.find(node => node.node_name.toLowerCase().includes('tts'))
  const hasError = trace?.status === 'error'
  const turn = detail?.conversation_turn
  const userText = turn?.user_text || trace?.user_text || ''
  const assistantText = turn?.assistant_text || ''
  const assistantOrError = assistantText || detail?.error_msg || ''
  const prompt = userText || '等待下一次对话进入 trace。'
  const status = trace?.status ?? 'pending'
  const allowEstimate = !detail
  const missingNodeStatus: TraceNodeStatus = detail ? 'skipped' : trace ? 'success' : 'skipped'
  const memorySpan = findSpan(detail, ['memory'])
  const toolSpan = findSpan(detail, ['tool'])
  const llmSpan = findSpan(detail, ['llm', 'chat', 'model'])
  const ttsSpan = findSpan(detail, ['tts', 'speech'])
  const outputSpan = findSpan(detail, ['output', 'response']) ?? findLastSpan(detail)

  return [
    {
      id: 'input',
      label: 'Input',
      role: '用户输入',
      status: trace ? 'success' : 'skipped',
      durationMs: 0,
      input: formatPayload(userText, '还没有采集到原始输入。'),
      output: prompt,
      attributes: [
        { label: 'type', value: turn?.input_type ?? trace?.input_type ?? 'unknown' },
        { label: 'session', value: turn?.session_id ?? trace?.session_id ?? '-' },
      ],
      events: ['message.received', 'state.initialized'],
    },
    {
      id: 'memory',
      label: 'Memory',
      role: '记忆检索',
      status: normalizeNodeStatus(memorySpan?.status, missingNodeStatus),
      durationMs: normalizeDuration(
        memorySpan?.duration_ms,
        allowEstimate ? Math.max(42, Math.round(totalDuration * 0.08)) : 0
      ),
      input: formatPayload(memorySpan?.input_summary ?? prompt, '没有采集到记忆节点输入。'),
      output: formatPayload(memorySpan?.output_summary, trace ? '未采集 memory output_summary。' : 'No trace selected'),
      attributes: [
        { label: 'span', value: memorySpan?.span_id ?? '-' },
        { label: 'strategy', value: 'hybrid search' },
      ],
      events: parseEvents(memorySpan) ?? ['memory.query', 'memory.merge_context'],
    },
    {
      id: 'tools',
      label: 'Tools',
      role: '工具调用',
      status: toolSpan ? normalizeNodeStatus(toolSpan.status, 'success') : 'skipped',
      durationMs: normalizeDuration(toolSpan?.duration_ms, 0),
      input: formatPayload(toolSpan?.input_summary, trace ? '本轮没有工具节点输入。' : 'No trace selected'),
      output: formatPayload(toolSpan?.output_summary, trace ? '本轮无外部工具调用。' : 'No trace selected'),
      attributes: [
        { label: 'calls', value: toolSpan ? '1' : '0' },
        { label: 'policy', value: 'auto' },
      ],
      events: parseEvents(toolSpan) ?? ['tool.router.skip'],
    },
    {
      id: 'llm',
      label: 'LLM',
      role: '推理生成',
      status: normalizeNodeStatus(llmSpan?.status, missingNodeStatus),
      durationMs: normalizeDuration(
        llmSpan?.duration_ms,
        allowEstimate ? Math.round(llmStats?.avg_duration_ms ?? totalDuration * 0.42) : 0
      ),
      input: formatPayload(llmSpan?.input_summary, trace ? prompt : 'No trace selected'),
      output: formatPayload(llmSpan?.output_summary ?? ttsSpan?.input_summary ?? assistantText, trace ? '未采集 llm output_summary。' : 'No trace selected'),
      attributes: [
        { label: 'span', value: llmSpan?.span_id ?? '-' },
        { label: 'provider', value: 'active llm service' },
      ],
      events: parseEvents(llmSpan) ?? ['llm.request.start', 'llm.stream.delta', 'llm.request.end'],
    },
    {
      id: 'tts',
      label: 'TTS',
      role: '语音合成',
      status: normalizeNodeStatus(ttsSpan?.status, !trace ? 'skipped' : hasError && !detail ? 'error' : missingNodeStatus),
      durationMs: normalizeDuration(
        ttsSpan?.duration_ms,
        allowEstimate ? Math.round(ttsStats?.avg_duration_ms ?? totalDuration * 0.36) : 0
      ),
      input: formatPayload(ttsSpan?.input_summary ?? llmSpan?.output_summary ?? assistantText, trace ? 'TTS 未保存输入摘要。' : 'No trace selected'),
      output: formatPayload(ttsSpan?.output_summary ?? detail?.error_msg, hasError ? '未采集 tts output_summary。' : '未采集 tts output_summary。'),
      attributes: [
        { label: 'voice', value: 'persona default' },
        { label: 'retryable', value: hasError ? 'yes' : 'no' },
      ],
      events: parseEvents(ttsSpan) ?? (hasError
        ? ['tts.request.start', 'tts.provider.error', 'trace.mark_error']
        : ['tts.request.start', 'tts.audio.ready']),
    },
    {
      id: 'output',
      label: 'Output',
      role: '响应出口',
      status: outputSpan ? normalizeNodeStatus(outputSpan.status, hasError ? 'warning' : 'success') : missingNodeStatus,
      durationMs: normalizeDuration(
        outputSpan?.duration_ms,
        allowEstimate ? Math.max(16, Math.round(totalDuration * 0.04)) : 0
      ),
      input: formatPayload(outputSpan?.input_summary ?? ttsSpan?.output_summary ?? llmSpan?.output_summary, hasError ? 'partial response' : 'text + audio + expression'),
      output: formatPayload(outputSpan?.output_summary ?? assistantOrError, status === 'success' ? '未采集 output_summary。' : '未采集 output_summary。'),
      attributes: [
        { label: 'trace', value: trace?.trace_id ?? '-' },
        { label: 'status', value: status },
      ],
      events: parseEvents(outputSpan) ?? (hasError ? ['response.partial', 'debug.snapshot.saved'] : ['response.sent', 'trace.closed']),
    },
  ]
}

function findSpan(detail: TraceDetail | null, keywords: string[]) {
  if (!detail) return null
  return detail.spans.find(span => {
    const nodeName = span.node_name.toLowerCase()
    return keywords.some(keyword => nodeName.includes(keyword))
  }) ?? null
}

function findLastSpan(detail: TraceDetail | null) {
  if (!detail?.spans.length) return null
  return detail.spans[detail.spans.length - 1]
}

function normalizeNodeStatus(status: string | null | undefined, fallback: TraceNodeStatus): TraceNodeStatus {
  if (status === 'success' || status === 'error') return status
  if (status === 'warning') return 'warning'
  if (status === 'skipped') return 'skipped'
  return fallback
}

function normalizeDuration(duration: number | null | undefined, fallback: number) {
  return Math.round(duration ?? fallback ?? 0)
}

function formatPayload(value: string | null | undefined, fallback: string) {
  const text = value?.trim()
  return text || fallback
}

function parseEvents(span: TraceSpan | null) {
  if (!span?.events) return null
  try {
    const events = JSON.parse(span.events)
    if (!Array.isArray(events)) return null
    return events.map((event) => {
      if (typeof event === 'string') return event
      if (event && typeof event === 'object' && 'name' in event) {
        return String(event.name)
      }
      return JSON.stringify(event)
    })
  } catch {
    return [span.events]
  }
}

function statusLabel(status: TraceNodeStatus | Trace['status']) {
  const labels: Record<string, string> = {
    success: 'OK',
    warning: 'WARN',
    error: 'FAIL',
    skipped: 'SKIP',
    pending: 'RUN',
  }
  return labels[status] ?? status.toUpperCase()
}

function formatDuration(duration?: number) {
  if (!duration) return '0 ms'
  if (duration >= 1000) return `${(duration / 1000).toFixed(2)} s`
  return `${Math.round(duration)} ms`
}

function formatTime(value?: string) {
  if (!value) return '--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}
</script>

<template>
  <div class="trace-dashboard">
    <header class="trace-hero">
      <div>
        <p class="eyebrow">Trace Debug Dashboard</p>
        <h1>对话链路观测</h1>
        <p class="summary">
          每次对话按节点展开，优先回答“这一次为什么坏了”，再决定是否全量重试。
        </p>
      </div>

      <div class="hero-actions">
        <button class="icon-btn" data-testid="newer-trace" :disabled="!canGoNewer" @click="goNewer">
          <span aria-hidden="true">←</span>
          <span class="sr-only">上一条更新的 trace</span>
        </button>
        <button class="icon-btn" data-testid="older-trace" :disabled="!canGoOlder" @click="goOlder">
          <span aria-hidden="true">→</span>
          <span class="sr-only">上一条更旧的 trace</span>
        </button>
        <button class="ghost-btn" :disabled="selectedTraceIndex === 0" @click="goLatest">
          Latest
        </button>
        <button class="primary-btn" @click="store.fetchAll">
          全量重试
        </button>
      </div>
    </header>

    <section class="status-strip">
      <div class="metric">
        <span>当前状态</span>
        <strong :class="`tone-${healthTone}`">
          {{ selectedTrace ? statusLabel(selectedTrace.status) : 'EMPTY' }}
        </strong>
      </div>
      <div class="metric">
        <span>耗时</span>
        <strong>{{ formatDuration(selectedTrace?.total_duration_ms) }}</strong>
      </div>
      <div class="metric">
        <span>节点</span>
        <strong>{{ executedNodeCount }}/{{ topology.length }}</strong>
      </div>
      <div class="metric">
        <span>失败点</span>
        <strong>{{ failedNode?.label ?? 'none' }}</strong>
      </div>
      <div class="metric">
        <span>更新时间</span>
        <strong>{{ selectedTraceTime }}</strong>
      </div>
    </section>

    <main class="workbench">
      <aside class="history-panel" :class="{ collapsed: !historyOpen }" aria-label="历史 Trace">
        <button
          class="history-toggle"
          data-testid="history-toggle"
          :aria-expanded="historyOpen"
          @click="historyOpen = !historyOpen"
        >
          <span class="history-toggle-main">
            <span class="eyebrow">历史 Trace</span>
            <strong>{{ selectedTrace?.user_text || '等待 trace' }}</strong>
            <small>{{ store.traces.length }} runs · {{ selectedTraceTime }}</small>
          </span>
          <span class="history-toggle-action">{{ historyOpen ? '收起' : '展开' }}</span>
        </button>

        <div v-if="historyOpen" class="trace-list" data-testid="history-traces">
          <button
            v-for="(trace, index) in store.traces"
            :key="trace.trace_id"
            class="trace-row"
            :class="{ active: index === selectedTraceIndex }"
            @click="selectTrace(index)"
          >
            <span class="row-status" :class="`status-${trace.status}`">{{ statusLabel(trace.status) }}</span>
            <span class="row-main">
              <strong>{{ trace.user_text || trace.trace_id }}</strong>
              <small>{{ formatTime(trace.created_at) }} · {{ formatDuration(trace.total_duration_ms) }}</small>
            </span>
          </button>
          <div v-if="!store.traces.length" class="empty-state">
            暂无 trace，下一次对话完成后会显示在这里。
          </div>
        </div>
      </aside>

      <section class="graph-panel">
        <div class="graph-toolbar">
          <div>
            <p class="eyebrow">Flow Graph</p>
            <h2>{{ selectedTrace?.user_text || '等待对话 trace' }}</h2>
          </div>
          <span class="trace-id">{{ selectedTrace?.trace_id ?? 'no-trace' }}</span>
        </div>

        <div class="flow-canvas" aria-label="对话节点流程">
          <template v-for="(node, index) in traceNodes" :key="node.id">
            <button
              class="flow-node"
              :class="[`node-${node.status}`, { selected: selectedNodeId === node.id }]"
              :data-testid="`trace-node-${node.id}`"
              @click="selectNode(node.id)"
            >
              <span class="node-topline">
                <span>{{ node.label }}</span>
                <small>{{ statusLabel(node.status) }}</small>
              </span>
              <strong>{{ node.role }}</strong>
              <span>{{ formatDuration(node.durationMs) }}</span>
            </button>
            <div v-if="index < traceNodes.length - 1" class="flow-edge" aria-hidden="true">
              <span />
            </div>
          </template>
        </div>

        <div class="data-flow">
          <div>
            <span>输入</span>
            <p>{{ selectedNode?.input }}</p>
          </div>
          <div>
            <span>输出</span>
            <p>{{ selectedNode?.output }}</p>
          </div>
        </div>
      </section>

      <aside class="detail-panel" aria-label="节点详情">
        <div class="panel-heading">
          <p class="eyebrow">节点详情</p>
          <span v-if="selectedNode" :class="`status-pill status-${selectedNode.status}`">
            {{ statusLabel(selectedNode.status) }}
          </span>
        </div>

        <template v-if="selectedNode">
          <h2>{{ selectedNode.label }}</h2>
          <p class="detail-role">{{ selectedNode.role }}</p>

          <div class="attribute-grid">
            <div v-for="item in selectedNode.attributes" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
            <div>
              <span>duration</span>
              <strong>{{ formatDuration(selectedNode.durationMs) }}</strong>
            </div>
          </div>

          <div class="event-list">
            <span>数据流事件</span>
            <ol>
              <li v-for="event in selectedNode.events" :key="event">{{ event }}</li>
            </ol>
          </div>
        </template>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.trace-dashboard {
  min-height: 100%;
  padding: 24px;
  overflow: auto;
  color: var(--c-text);
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--c-panel) 92%, transparent),
      color-mix(in srgb, var(--c-bg) 96%, transparent)
    ),
    var(--c-bg);
}

.trace-hero,
.status-strip,
.history-panel,
.graph-panel,
.detail-panel {
  border: 1px solid var(--c-border);
  border-radius: 16px;
  background: color-mix(in srgb, var(--c-panel) 74%, transparent);
  box-shadow: var(--shadow-glass);
  backdrop-filter: blur(16px);
}

.trace-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--c-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  color: var(--c-text);
  font-size: 28px;
  line-height: 1.2;
}

.summary {
  margin-top: 8px;
  max-width: 620px;
  color: var(--c-text-dim);
  font-size: 14px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

button {
  border: 0;
  color: inherit;
  font: inherit;
}

.icon-btn,
.ghost-btn,
.primary-btn {
  min-height: 34px;
  border: 1px solid var(--c-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--c-text) 6%, transparent);
  transition: background 200ms var(--ease-out-expo), border-color 200ms var(--ease-out-expo), transform 200ms var(--ease-out-expo);
}

.icon-btn {
  width: 36px;
  font-size: 17px;
}

.ghost-btn,
.primary-btn {
  padding: 0 14px;
  font-size: 12px;
  font-weight: 700;
}

.primary-btn {
  border-color: color-mix(in srgb, var(--c-warning) 45%, transparent);
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--c-warning) 24%, transparent),
    color-mix(in srgb, var(--c-accent) 18%, transparent)
  );
  color: var(--c-text);
}

.icon-btn:not(:disabled):hover,
.ghost-btn:not(:disabled):hover,
.primary-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: var(--c-border-bright);
  background: color-mix(in srgb, var(--c-text) 11%, transparent);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.status-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 1px;
  margin-top: 14px;
  overflow: hidden;
}

.metric {
  display: flex;
  min-height: 72px;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  padding: 14px 16px;
  background: color-mix(in srgb, var(--c-text) 3%, transparent);
}

.metric span,
.panel-heading span,
.detail-role,
.event-list span,
.attribute-grid span,
.flow-node span,
.data-flow span {
  color: var(--c-text-muted);
  font-size: 11px;
}

.metric strong {
  font-size: 16px;
}

.tone-success,
.status-success,
.node-success .node-topline small {
  color: var(--c-success);
}

.tone-error,
.status-error,
.node-error .node-topline small {
  color: var(--c-error);
}

.tone-warning,
.status-warning,
.node-warning .node-topline small {
  color: var(--c-warning);
}

.tone-idle,
.status-skipped,
.status-pending,
.node-skipped .node-topline small {
  color: var(--c-text-muted);
}

.workbench {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) minmax(260px, 320px);
  gap: 14px;
  margin-top: 14px;
  min-height: 560px;
}

.history-panel {
  grid-column: 1 / -1;
}

.history-panel,
.graph-panel,
.detail-panel {
  padding: 18px;
}

.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-panel.collapsed {
  padding: 12px 16px;
}

.panel-heading,
.graph-toolbar,
.node-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.history-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  min-height: 58px;
  padding: 0;
  background: transparent;
  text-align: left;
}

.history-toggle-main {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.history-toggle-main .eyebrow {
  margin-bottom: 0;
}

.history-toggle-main strong {
  overflow: hidden;
  color: var(--c-text);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-toggle-main small,
.history-toggle-action {
  color: var(--c-text-muted);
  font-size: 11px;
}

.history-toggle-action {
  flex-shrink: 0;
  padding: 8px 12px;
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--c-text) 5%, transparent);
  font-weight: 700;
}

.trace-list {
  display: grid;
  gap: 12px;
  margin-top: 14px;
  max-height: 260px;
  overflow: auto;
  padding-right: 4px;
}

.trace-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 10px;
  width: 100%;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: color-mix(in srgb, var(--c-text) 4.5%, transparent);
  text-align: left;
  transition: background 200ms var(--ease-out-expo), border-color 200ms var(--ease-out-expo);
}

.trace-row.active,
.trace-row:hover {
  border-color: color-mix(in srgb, var(--c-accent) 42%, transparent);
  background: color-mix(in srgb, var(--c-accent) 9%, transparent);
}

.row-status {
  font-size: 10px;
  font-weight: 800;
}

.row-main {
  min-width: 0;
}

.row-main strong {
  display: block;
  overflow: hidden;
  color: var(--c-text);
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-main small {
  display: block;
  margin-top: 4px;
  color: var(--c-text-muted);
  font-size: 11px;
}

.empty-state {
  padding: 16px;
  border: 1px dashed var(--c-border);
  border-radius: 12px;
  color: var(--c-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.graph-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.graph-toolbar h2 {
  max-width: 640px;
  overflow: hidden;
  color: var(--c-text);
  font-size: 17px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-id {
  flex-shrink: 0;
  padding: 7px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--c-text) 6%, transparent);
  color: var(--c-text-muted);
  font-size: 11px;
}

.flow-canvas {
  display: flex;
  align-items: center;
  gap: 0;
  min-height: 330px;
  padding: 26px 18px;
  border: 1px solid color-mix(in srgb, var(--c-text) 7%, transparent);
  border-radius: 16px;
  background:
    linear-gradient(color-mix(in srgb, var(--c-text) 3.5%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--c-text) 3.5%, transparent) 1px, transparent 1px),
    color-mix(in srgb, var(--c-bg) 48%, transparent);
  background-size: 28px 28px;
}

.flow-node {
  position: relative;
  z-index: 1;
  display: flex;
  flex: 1 1 110px;
  min-height: 116px;
  min-width: 104px;
  flex-direction: column;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--c-border);
  border-radius: 14px;
  background: color-mix(in srgb, var(--c-panel) 92%, transparent);
  text-align: left;
  box-shadow: 0 18px 34px color-mix(in srgb, var(--c-bg) 72%, transparent);
  transition: transform 200ms var(--ease-out-expo), border-color 200ms var(--ease-out-expo), box-shadow 200ms var(--ease-out-expo);
}

.flow-node strong {
  color: var(--c-text);
  font-size: 14px;
}

.flow-node.selected {
  transform: translateY(-4px);
  border-color: color-mix(in srgb, var(--c-warning) 58%, transparent);
  box-shadow:
    0 22px 42px color-mix(in srgb, var(--c-bg) 76%, transparent),
    0 0 0 1px color-mix(in srgb, var(--c-warning) 16%, transparent);
}

.node-error {
  border-color: color-mix(in srgb, var(--c-error) 44%, transparent);
}

.node-warning {
  border-color: color-mix(in srgb, var(--c-warning) 34%, transparent);
}

.node-skipped {
  opacity: 0.64;
}

.flow-edge {
  flex: 0 0 34px;
  position: relative;
  height: 2px;
  margin: 0 -3px;
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--c-accent) 8%, transparent),
    color-mix(in srgb, var(--c-accent) 70%, transparent)
  );
}

.flow-edge span {
  position: absolute;
  top: 50%;
  right: -1px;
  width: 8px;
  height: 8px;
  border-top: 2px solid color-mix(in srgb, var(--c-accent) 80%, transparent);
  border-right: 2px solid color-mix(in srgb, var(--c-accent) 80%, transparent);
  transform: translateY(-50%) rotate(45deg);
}

.data-flow {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.data-flow div,
.attribute-grid div,
.event-list {
  border: 1px solid var(--c-border);
  border-radius: 12px;
  background: color-mix(in srgb, var(--c-text) 4.5%, transparent);
}

.data-flow div {
  padding: 14px;
}

.data-flow p {
  margin-top: 8px;
  color: var(--c-text-dim);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.detail-panel h2 {
  color: var(--c-text);
  font-size: 22px;
}

.status-pill {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  font-size: 10px;
  font-weight: 800;
}

.attribute-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.attribute-grid div {
  padding: 11px 12px;
}

.attribute-grid strong {
  display: block;
  margin-top: 5px;
  color: var(--c-text);
  font-size: 12px;
  line-height: 1.45;
}

.event-list {
  padding: 14px;
}

.event-list ol {
  margin: 10px 0 0;
  padding-left: 18px;
  color: var(--c-text-dim);
  font-size: 12px;
  line-height: 1.85;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 1180px) {
  .workbench {
    grid-template-columns: 1fr;
  }

  .flow-canvas {
    flex-direction: column;
    gap: 10px;
  }

  .flow-node {
    width: 100%;
  }

  .flow-edge {
    flex: 0 0 28px;
    width: 2px;
    height: 28px;
    margin: -2px auto;
    background: linear-gradient(
      180deg,
      color-mix(in srgb, var(--c-accent) 8%, transparent),
      color-mix(in srgb, var(--c-accent) 70%, transparent)
    );
  }

  .flow-edge span {
    top: auto;
    right: 50%;
    bottom: -1px;
    transform: translateX(50%) rotate(135deg);
  }
}

@media (max-width: 760px) {
  .trace-dashboard {
    padding: 14px;
  }

  .trace-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .hero-actions {
    justify-content: flex-start;
  }

  .status-strip,
  .data-flow {
    grid-template-columns: 1fr;
  }

  .graph-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .graph-toolbar h2 {
    white-space: normal;
  }
}
</style>

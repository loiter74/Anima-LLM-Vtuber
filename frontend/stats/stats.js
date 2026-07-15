const API_BASE = window.location.origin

// === KPI ===
async function fetchOverview() {
  const res = await fetch(`${API_BASE}/api/stats/overview`)
  const data = await res.json()

  document.getElementById('total-requests').textContent = data.total_requests.toLocaleString()
  document.getElementById('success-rate').textContent = data.success_rate + '%'
  document.getElementById('p95-latency').textContent = data.avg_duration_ms
    ? data.avg_duration_ms.toFixed(0) + 'ms avg'
    : '-'
}

async function fetchErrorRate() {
  const res = await fetch(`${API_BASE}/api/stats/nodes`)
  const data = await res.json()
  const totalErrors = data.reduce((sum, n) => sum + (n.failure_count || 0), 0)
  const totalCalls = data.reduce((sum, n) => sum + (n.operation_count || 0), 0)
  const rate = totalCalls > 0 ? ((totalErrors / totalCalls) * 100).toFixed(1) + '%' : '0%'
  document.getElementById('error-rate').textContent = rate
}

// === Chart ===
let nodeChart = null

async function fetchNodeStats() {
  const res = await fetch(`${API_BASE}/api/stats/nodes`)
  const data = await res.json()

  if (!data.length) return

  const labels = data.map((d) => `${d.layer} · ${d.name}`)
  const durations = data.map((d) => d.avg_duration_ms)
  const errors = data.map((d) => d.failure_count)

  if (nodeChart) {
    nodeChart.data.labels = labels
    nodeChart.data.datasets[0].data = durations
    nodeChart.data.datasets[1].data = errors
    nodeChart.update()
    return
  }

  nodeChart = new Chart(document.getElementById('node-chart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Avg Duration (ms)',
          data: durations,
          backgroundColor: '#38bdf8',
          borderRadius: 4,
        },
        {
          label: 'Errors',
          data: errors,
          backgroundColor: '#f87171',
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      scales: {
        x: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
        y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
      },
      plugins: {
        legend: { labels: { color: '#e2e8f0' } },
      },
    },
  })
}

// === Traces ===
async function fetchTraces() {
  const res = await fetch(`${API_BASE}/api/stats/traces?limit=50`)
  const data = await res.json()

  const tbody = document.getElementById('traces-body')
  tbody.innerHTML = ''

  data.forEach((trace) => {
    const tr = document.createElement('tr')
    tr.className = 'trace-row'
    tr.onclick = () => showTraceDetail(trace.trace_id)

    const time = trace.started_at ? new Date(trace.started_at * 1000).toLocaleTimeString() : '-'
    const statusClass = trace.outcome === 'success' ? 'status-success' : 'status-error'

    tr.innerHTML = `
            <td>${time}</td>
            <td>${trace.input_type}</td>
            <td>${escapeHtml(`${trace.runtime_profile} · ${trace.trace_id}`)}</td>
            <td>${trace.duration_ms ? trace.duration_ms.toFixed(0) + 'ms' : '-'}</td>
            <td class="${statusClass}">${trace.outcome || 'running'}</td>
        `
    tbody.appendChild(tr)
  })
}

// === Trace Detail (with Flame Chart) ===
async function showTraceDetail(traceId) {
  // Fetch the tree endpoint (includes flat spans + tree structure)
  const res = await fetch(`${API_BASE}/api/stats/traces/${traceId}/tree`)
  const data = await res.json()
  if (data.error) {
    alert(data.error)
    return
  }

  const detail = document.getElementById('trace-detail')
  const time = data.started_at ? new Date(data.started_at * 1000).toLocaleString() : '-'

  const totalDuration = data.duration_ms || 1
  const treeHtml = renderTree(data.operation_tree || [], totalDuration, 0)

  detail.innerHTML = `
        <div class="trace-meta">
            <div class="trace-meta-item">
                <label>Trace ID</label>
                <span>${data.trace_id.slice(0, 8)}...</span>
            </div>
            <div class="trace-meta-item">
                <label>Total Duration</label>
                <span>${totalDuration.toFixed(0) + 'ms'}</span>
            </div>
            <div class="trace-meta-item">
                <label>Status</label>
                <span class="${data.outcome === 'success' ? 'status-success' : 'status-error'}">${data.outcome || 'running'}</span>
            </div>
            <div class="trace-meta-item">
                <label>Time</label>
                <span>${time}</span>
            </div>
        </div>
        <h3>Operation Tree (${data.operations.length} operations)</h3>
        <div class="flame-chart">${treeHtml}</div>
        <h3>Operation List</h3>
        <ul class="span-list">
            ${data.operations
              .map(
                (s) => `
                <li class="span-item">
                    <span class="span-name">${escapeHtml(s.name)}</span>
                    <span class="span-duration">${s.duration_ms ? s.duration_ms.toFixed(1) + 'ms' : '-'}</span>
                    <span class="span-summary">${escapeHtml([s.provider, s.model, s.status].filter(Boolean).join(' · ') || '-')}</span>
                </li>
            `,
              )
              .join('')}
        </ul>
    `

  document.getElementById('trace-modal').classList.remove('hidden')
}

// ── Flame Chart Renderer ──

const SPAN_COLORS = [
  '#38bdf8',
  '#f472b6',
  '#a78bfa',
  '#34d399',
  '#fb923c',
  '#fbbf24',
  '#818cf8',
  '#2dd4bf',
  '#f87171',
  '#e879f9',
  '#22d3ee',
  '#facc15',
]

function renderTree(nodes, totalDuration, depth) {
  if (!nodes || nodes.length === 0) return ''
  const depthEm = Math.min(depth * 1.2, 6)
  let html = ''
  nodes.forEach((node) => {
    const dur = node.duration_ms || 0
    const pct = totalDuration > 0 ? (dur / totalDuration) * 100 : 0
    const color = SPAN_COLORS[depth % SPAN_COLORS.length]
    const label = `${node.name} — ${dur.toFixed(1)}ms`
    html += `
            <div class="flame-bar-wrap" style="margin-left: ${depthEm}em;">
                <div class="flame-bar" style="width: ${Math.max(pct, 2)}%; background: ${color};"
                     title="${escapeHtml(label)}">
                    <span class="flame-label">${escapeHtml(label)}</span>
                </div>
            </div>
            ${renderTree(node.children || [], totalDuration, depth + 1)}
        `
  })
  return html
}

function closeModal() {
  document.getElementById('trace-modal').classList.add('hidden')
}

// Close modal on background click
document.getElementById('trace-modal').addEventListener('click', function (e) {
  if (e.target === this) closeModal()
})

function escapeHtml(text) {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

// === Auto Refresh ===
async function refreshAll() {
  try {
    await Promise.all([fetchOverview(), fetchNodeStats(), fetchTraces(), fetchErrorRate()])
  } catch (e) {
    console.error('Refresh failed:', e)
  }
}

// Init
refreshAll()
setInterval(refreshAll, 5000)

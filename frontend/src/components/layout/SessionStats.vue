<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const sessionDuration = ref('0m 0s')
const messageCount = ref(0)
const memoryAtoms = ref(0)
const avgLatency = ref(0)

let startTime: number
let timerInterval: ReturnType<typeof setInterval>

function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  }
  return `${minutes}m ${seconds % 60}s`
}

function updateTimer() {
  const elapsed = Date.now() - startTime
  sessionDuration.value = formatDuration(elapsed)
}

onMounted(() => {
  startTime = Date.now()
  timerInterval = setInterval(updateTimer, 1000)

  // Simulate stats (replace with real data from store)
  messageCount.value = 47
  memoryAtoms.value = 128
  avgLatency.value = 230
})

onUnmounted(() => {
  if (timerInterval) {
    clearInterval(timerInterval)
  }
})
</script>

<template>
  <div class="session-stats">
    <div class="section-title">Session Stats</div>

    <div class="stat-row">
      <span class="stat-icon">⏱️</span>
      <span class="stat-label">Session</span>
      <span class="stat-value">{{ sessionDuration }}</span>
    </div>

    <div class="stat-row">
      <span class="stat-icon">💬</span>
      <span class="stat-label">Messages</span>
      <span class="stat-value">{{ messageCount }}</span>
    </div>

    <div class="stat-row">
      <span class="stat-icon">🧠</span>
      <span class="stat-label">Memory</span>
      <span class="stat-value">{{ memoryAtoms }} atoms</span>
    </div>

    <div class="stat-row">
      <span class="stat-icon">⚡</span>
      <span class="stat-label">Avg Latency</span>
      <span class="stat-value">{{ avgLatency }}ms</span>
    </div>
  </div>
</template>

<style scoped>
.session-stats {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}

.section-title {
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--c-text-muted);
  font-weight: 600;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

.stat-icon {
  font-size: 14px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.stat-label {
  font-size: 12px;
  color: var(--c-text-dim);
  flex: 1;
}

.stat-value {
  font-size: 13px;
  color: var(--c-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>

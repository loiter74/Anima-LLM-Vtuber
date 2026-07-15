<script setup lang="ts">
import { computed } from 'vue'
import { Bar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js'
import { useDashboardStore } from '../../stores/dashboardStore'

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend)

const store = useDashboardStore()

const chartData = computed(() => ({
  labels: store.nodeStats.map((n) => `${n.layer} · ${n.name}`),
  datasets: [
    {
      label: 'Avg Duration (ms)',
      data: store.nodeStats.map((n) => n.avg_duration_ms),
      backgroundColor: 'rgba(99, 102, 241, 0.7)',
      borderColor: 'rgb(99, 102, 241)',
      borderWidth: 1,
    },
  ],
}))

const chartOptions = {
  responsive: true,
  indexAxis: 'y' as const,
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: {
      grid: { color: 'rgba(255,255,255,0.05)' },
      ticks: { color: '#9ca3af' },
    },
    y: {
      grid: { display: false },
      ticks: { color: '#9ca3af' },
    },
  },
}
</script>

<template>
  <div class="bg-c-card/50 rounded-xl p-4 border border-c-border">
    <h3 class="text-sm font-medium text-c-text-dim mb-4">Pipeline Latency Breakdown</h3>
    <Bar v-if="store.nodeStats.length" :data="chartData" :options="chartOptions" />
    <div v-else class="text-c-text-muted text-center py-12 text-sm">No data yet</div>
  </div>
</template>

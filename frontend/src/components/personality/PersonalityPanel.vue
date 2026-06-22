<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { usePersonalityStore } from '@/stores/personality'
import { Radar } from 'vue-chartjs'
import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

const store = usePersonalityStore()

function cssToken(name: string): string {
  if (typeof window === 'undefined') return ''
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function token(name: string): string {
  return cssToken(name) || `var(${name})`
}

onMounted(() => {
  store.fetchAvailablePersonas()
})

const collapsed = ref(false)
const mbtiCollapsed = ref(false)
const selectedPersona = ref('')

const chartData = computed(() => {
  const d = store.mbtiDimensions ?? { ei: 50, sn: 50, tf: 50, jp: 50 }
  return {
    labels: ['E/I', 'S/N', 'T/F', 'J/P'],
    datasets: [
      {
        label: 'MBTI',
        data: [d.ei, d.sn, d.tf, d.jp],
        backgroundColor: token('--c-ai-bubble'),
        borderColor: token('--c-border-accent'),
        pointBackgroundColor: token('--c-accent'),
        pointBorderColor: token('--c-bg'),
        pointBorderWidth: 1.5,
        pointRadius: 4,
        pointHoverRadius: 6,
        borderWidth: 1.5,
        fill: true,
      },
    ],
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    r: {
      min: 0,
      max: 100,
      ticks: {
        stepSize: 25,
        backdropColor: 'transparent',
        color: token('--c-text-muted'),
        font: { size: 10 },
      },
      grid: {
        color: token('--c-border'),
      },
      angleLines: {
        color: token('--c-border'),
      },
      pointLabels: {
        color: token('--c-text-dim'),
        font: { size: 11, weight: 500 },
      },
    },
  },
  plugins: {
    legend: { display: false },
    tooltip: { enabled: false },
  },
}

const computedMbtiType = computed(() => {
  if (store.mbtiType) return store.mbtiType
  if (!store.mbtiDimensions) return null
  const { ei, sn, tf, jp } = store.mbtiDimensions
  return `${ei >= 50 ? 'E' : 'I'}${sn >= 50 ? 'S' : 'N'}${tf >= 50 ? 'T' : 'F'}${jp >= 50 ? 'J' : 'P'}`
})

const dimensions = computed(() => {
  const d = store.mbtiDimensions ?? { ei: 50, sn: 50, tf: 50, jp: 50 }
  return [
    { label: 'E/I', val: d.ei, color: token('--c-violet'), left: '内向 I', right: '外向 E' },
    { label: 'S/N', val: d.sn, color: token('--c-blue'), left: '实感 S', right: '直觉 N' },
    { label: 'T/F', val: d.tf, color: token('--c-gold'), left: '共情 F', right: '理性 T' },
    { label: 'J/P', val: d.jp, color: token('--c-mint'), left: '随性 P', right: '计划 J' },
  ]
})

watch(() => store.availablePersonas, (personas) => {
  if (personas.length > 0 && !selectedPersona.value) {
    selectedPersona.value = personas[0]
  }
}, { immediate: true })

function applyPersona(): void {
  if (selectedPersona.value) {
    store.setPersona(selectedPersona.value)
  }
}

function toggleMode(): void {
  store.setMode(store.currentMode === 'default' ? 'streaming' : 'default')
}
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="flex items-center gap-2 px-5 py-4 border-b border-c-border/60 shrink-0">
      <span class="text-sm">🎭</span>
      <span class="text-sm font-medium text-c-text">人格配置</span>
      <div class="flex-1" />
      <button
        class="w-7 h-7 flex items-center justify-center rounded-lg bg-c-bg/50 text-c-text-dim hover:text-c-text hover:bg-c-bg/70 transition-colors"
        @click="collapsed = !collapsed"
      >
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          :class="collapsed ? '' : 'rotate-180'"
          class="transition-transform"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
    </div>

    <div v-show="!collapsed" class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
      <!-- Current mode badge -->
      <div>
        <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2 block">当前模式</label>
        <span
          class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium"
          :class="store.currentMode === 'streaming'
            ? 'bg-c-accent/20 text-c-accent'
            : 'bg-c-card/80 text-c-text-dim'"
        >
          {{ store.currentMode === 'streaming' ? '流式' : '默认' }}
        </span>
      </div>

      <!-- Persona switcher -->
      <div>
        <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2 block">角色人设</label>
        <select
          v-model="selectedPersona"
          class="w-full px-3 py-2 rounded-xl bg-c-bg/80 border border-c-border/40 text-sm text-c-text
                 focus:outline-none focus:border-c-accent/50 transition-colors appearance-none cursor-pointer"
        >
          <option value="" disabled>选择人设...</option>
          <option v-for="p in store.availablePersonas" :key="p" :value="p">{{ p }}</option>
        </select>
        <button
          class="mt-2 w-full px-3 py-2 rounded-xl text-xs font-medium transition-all
                 flex items-center justify-center gap-1.5"
          :class="store.personaSuccess
            ? 'bg-c-success/20 text-c-success'
            : store.personaError
              ? 'bg-c-error/20 text-c-error'
              : 'bg-c-accent/20 text-c-accent hover:bg-c-accent/30'"
          :disabled="store.personaLoading"
          @click="applyPersona"
        >
          <svg v-if="store.personaLoading" class="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span v-else-if="store.personaSuccess">✓ 已应用</span>
          <span v-else-if="store.personaError">{{ store.personaError }}</span>
          <span v-else>应用</span>
        </button>
      </div>

      <!-- Streaming mode toggle -->
      <div>
        <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2 block">流式模式</label>
        <div class="flex items-center justify-between bg-c-card/80 rounded-xl px-3 py-2.5">
          <span class="text-xs text-c-text">{{ store.currentMode === 'streaming' ? '已开启' : '已关闭' }}</span>
          <button
            class="w-10 h-5 rounded-full transition-colors relative shrink-0"
            :class="[
              store.currentMode === 'streaming' ? 'bg-c-accent' : 'bg-c-bg/80 border border-c-border/40',
              store.modeLoading ? 'opacity-50 cursor-not-allowed' : ''
            ]"
            :disabled="store.modeLoading"
            @click="toggleMode"
          >
            <span
              class="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform duration-200"
              :class="store.currentMode === 'streaming' ? 'translate-x-[22px]' : 'translate-x-[2px]'"
            />
          </button>
        </div>
      </div>

      <!-- Memory influence slider -->
      <div>
        <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2 block">记忆影响度</label>
        <div class="bg-c-card/80 rounded-xl px-3 py-2.5">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-xs text-c-text-dim">影响权重</span>
            <span class="text-xs text-c-accent font-medium tabular-nums">{{ store.memoryInfluence.toFixed(1) }}</span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            :value="store.memoryInfluence"
            class="range-slider w-full"
            @input="store.setMemoryInfluence(Number(($event.target as HTMLInputElement).value))"
          />
          <div class="flex justify-between text-10px text-c-text-muted mt-1">
            <span>最小</span>
            <span>最大</span>
          </div>
        </div>
      </div>

      <!-- Current mood -->
      <div>
        <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2 block">当前情绪</label>
        <div class="bg-c-card/80 rounded-xl px-3 py-2.5 flex items-center gap-2">
          <span class="text-sm">💭</span>
          <span v-if="store.currentMood" class="text-sm text-c-text capitalize">{{ store.currentMood }}</span>
          <span v-else class="text-sm text-c-text-muted">暂无检测数据</span>
        </div>
      </div>

      <!-- MBTI -->
      <div>
        <div class="flex items-center justify-between mb-2">
          <label class="text-xs font-medium text-c-text-dim uppercase tracking-wider">MBTI 人格</label>
          <button
            class="w-7 h-7 flex items-center justify-center rounded-lg bg-c-bg/50 text-c-text-dim hover:text-c-text hover:bg-c-bg/70 transition-colors"
            @click="mbtiCollapsed = !mbtiCollapsed"
          >
            <svg
              width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              :class="mbtiCollapsed ? '' : 'rotate-180'"
              class="transition-transform"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        </div>

        <div v-show="!mbtiCollapsed" class="space-y-3">
          <!-- Type badge -->
          <div class="bg-c-card/80 rounded-xl px-3 py-2.5 flex items-center gap-2">
            <span v-if="computedMbtiType" class="text-sm font-bold text-c-accent">{{ computedMbtiType }}</span>
            <span v-else class="text-sm text-c-text-muted">暂无检测数据</span>
          </div>

          <!-- Radar chart -->
          <div class="bg-c-card/80 rounded-xl p-3" style="height: 200px">
            <Radar :data="chartData" :options="chartOptions" />
          </div>

          <!-- Dimension bars -->
          <div class="bg-c-card/80 rounded-xl px-3 py-2.5 space-y-2.5">
            <div v-for="dim in dimensions" :key="dim.label" class="space-y-1">
              <div class="flex items-center justify-between">
                <span class="text-10px text-c-text-muted">{{ dim.left }}</span>
                <span class="text-xs font-medium text-c-text-dim">{{ dim.label }}</span>
                <span class="text-10px text-c-text-muted">{{ dim.right }}</span>
              </div>
              <div class="flex items-center gap-2">
                <div class="flex-1 h-1.5 rounded-full bg-c-bg/80 overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all duration-300"
                    :style="{ width: dim.val + '%', background: dim.color }"
                  />
                </div>
                <span class="text-xs tabular-nums text-c-text-dim w-6 text-right shrink-0">{{ dim.val }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.range-slider {
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  border-radius: 999px;
  background: var(--c-border);
  cursor: pointer;
  outline: none;
}

.range-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--c-violet);
  box-shadow: 0 0 8px var(--c-violet-glow);
  transition: box-shadow 0.2s;
}

.range-slider::-webkit-slider-thumb:hover {
  box-shadow: var(--shadow-glow-violet);
}

.range-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--c-violet);
  border: none;
  box-shadow: 0 0 8px var(--c-violet-glow);
}

.range-slider::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: var(--c-border);
}
</style>

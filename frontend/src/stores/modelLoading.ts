import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ModelLoadingState, ModelStatusPayload } from '@/types/model-loading'

/**
 * Tracks model loading status from backend ModelLoadingManager.
 * Models transition: loading → loaded | error
 * The overlay is visible while any model is still loading.
 */
export const useModelLoadingStore = defineStore('modelLoading', () => {
  const models = ref<Map<string, ModelLoadingState>>(new Map())

  /** Models that haven't reached terminal state */
  const activeLoads = computed(() =>
    Array.from(models.value.values()).filter((m) => m.status === 'loading'),
  )

  /** True while warmup is in progress (any model still loading) */
  const isLoading = computed(() => activeLoads.value.length > 0)

  /** Overall progress 0..1 */
  const progress = computed(() => {
    const total = models.value.size
    if (total === 0) return 1
    const done = Array.from(models.value.values()).filter(
      (m) => m.status === 'loaded' || m.status === 'error',
    ).length
    return done / total
  })

  /** Human-readable summary */
  const summary = computed(() => {
    const loading = activeLoads.value
    if (loading.length === 0) return ''
    const names = loading.map((m) => m.service).join('、')
    return `正在加载 ${names} ...`
  })

  /** Tracked model names */
  const modelNames = computed(() => Array.from(models.value.keys()))

  function updateModelStatus(payload: ModelStatusPayload) {
    const { service, name, status, error } = payload
    models.value.set(name, { service, name, status, error })
  }

  function clear() {
    models.value.clear()
  }

  return {
    models,
    activeLoads,
    isLoading,
    progress,
    summary,
    modelNames,
    updateModelStatus,
    clear,
  }
})

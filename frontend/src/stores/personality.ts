import { defineStore } from 'pinia'
import { ref, onMounted, onUnmounted } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

export const usePersonalityStore = defineStore('personality', () => {
  const currentMode = ref<'default' | 'streaming'>('default')
  const currentMood = ref<string | null>(null)
  const availablePersonas = ref<string[]>([])
  const memoryInfluence = ref(0.3)
  const mbtiType = ref<string | null>(null)
  const mbtiDimensions = ref<{ ei: number; sn: number; tf: number; jp: number } | null>(null)

  // Loading states
  const personaLoading = ref(false)
  const personaSuccess = ref(false)
  const personaError = ref<string | null>(null)
  const modeLoading = ref(false)

  // Listen for persona:updated events to get MBTI data
  function setupListeners(): void {
    const socket = getSocket()
    if (!socket) return

    socket.on(Events.PERSONA.UPDATED, (data: { persona_name: string; mbti?: { type: string; dimensions: { ei: number; sn: number; tf: number; jp: number }; description: string } }) => {
      if (data.mbti) {
        mbtiType.value = data.mbti.type
        mbtiDimensions.value = data.mbti.dimensions
      } else {
        mbtiType.value = null
        mbtiDimensions.value = null
      }
    })
  }

  function cleanupListeners(): void {
    const socket = getSocket()
    if (!socket) return
    socket.off(Events.PERSONA.UPDATED)
  }

  async function fetchAvailablePersonas(): Promise<void> {
    const socket = getSocket()
    if (!socket) return

    socket.emit(Events.PERSONA.LIST, {}, (response: { personas: string[]; mbti?: { type: string; dimensions: { ei: number; sn: number; tf: number; jp: number }; description: string } }) => {
      availablePersonas.value = response.personas ?? []
      // Also update MBTI data from initial fetch
      if (response.mbti) {
        mbtiType.value = response.mbti.type
        mbtiDimensions.value = response.mbti.dimensions
      }
    })
  }

  async function setPersona(name: string): Promise<void> {
    const socket = getSocket()
    if (!socket) {
      personaError.value = '连接已断开，请重试'
      return
    }

    personaLoading.value = true
    personaError.value = null
    personaSuccess.value = false

    try {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('操作超时'))
        }, 5000)

        socket.emit(Events.PERSONA.SET, { persona_name: name }, (response: { error?: string }) => {
          clearTimeout(timeout)
          if (response?.error) {
            reject(new Error(response.error))
          } else {
            resolve()
          }
        })
      })

      personaSuccess.value = true
      setTimeout(() => {
        personaSuccess.value = false
      }, 1000)
    } catch (e) {
      personaError.value = e instanceof Error ? e.message : '切换失败'
      setTimeout(() => {
        personaError.value = null
      }, 3000)
    } finally {
      personaLoading.value = false
    }
  }

  async function setMode(mode: 'default' | 'streaming'): Promise<void> {
    const socket = getSocket()
    if (!socket) return

    modeLoading.value = true

    try {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('操作超时'))
        }, 5000)

        socket.emit(Events.PERSONA.SET_MODE, { mode }, (response: { error?: string }) => {
          clearTimeout(timeout)
          if (response?.error) {
            reject(new Error(response.error))
          } else {
            resolve()
          }
        })
      })

      currentMode.value = mode
    } catch (e) {
      // Mode change failed, don't update local state
      console.error('Failed to set mode:', e)
    } finally {
      modeLoading.value = false
    }
  }

  function setMood(mood: string | null): void {
    currentMood.value = mood
  }

  function setMemoryInfluence(value: number): void {
    memoryInfluence.value = Math.max(0, Math.min(1, value))
  }

  function setMbtiType(type: string | null): void {
    mbtiType.value = type
  }

  function setMbtiDimensions(dimensions: { ei: number; sn: number; tf: number; jp: number } | null): void {
    mbtiDimensions.value = dimensions
  }

  // Auto-setup listeners when store is created
  setupListeners()

  return {
    currentMode,
    currentMood,
    availablePersonas,
    memoryInfluence,
    mbtiType,
    mbtiDimensions,
    personaLoading,
    personaSuccess,
    personaError,
    modeLoading,
    fetchAvailablePersonas,
    setPersona,
    setMode,
    setMood,
    setMemoryInfluence,
    setMbtiType,
    setMbtiDimensions,
    setupListeners,
    cleanupListeners,
  }
})

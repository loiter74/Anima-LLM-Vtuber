import { defineStore } from 'pinia'
import { ref, onMounted, onUnmounted } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

export interface MinecraftStatus {
  connected: boolean
  username?: string
  error?: string
}

export interface MinecraftViewerStatus {
  status: 'waiting' | 'joined' | 'left' | 'error'
  username?: string
  error?: string
}

export interface BotState {
  health: number
  food: number
  position: { x: number; y: number; z: number }
  dimension: string
  biome: string
  time: string
  weather: string
  action: string
  actionTarget: string
  heldItem: string
  inventory: Array<{ name: string; count: number; slot: number }>
}

export const useMinecraftStore = defineStore('minecraft', () => {
  const connected = ref(false)
  const isConnecting = ref(false)
  const username = ref('')
  const error = ref('')

  // Viewer spectator state
  const viewerStatus = ref<'idle' | 'waiting' | 'joined' | 'left' | 'error'>('idle')
  const viewerUsername = ref('')

  // Bot state (real-time HUD data)
  const botState = ref<BotState>({
    health: 20,
    food: 20,
    position: { x: 0, y: 0, z: 0 },
    dimension: 'overworld',
    biome: 'unknown',
    time: 'day',
    weather: 'clear',
    action: 'idle',
    actionTarget: '',
    heldItem: 'empty hand',
    inventory: [],
  })

  let cleanup: (() => void) | null = null

  function setupListener(): void {
    const socket = getSocket()
    if (!socket) return

    const statusHandler = (data: MinecraftStatus) => {
      connected.value = data.connected
      isConnecting.value = false
      if (data.username) username.value = data.username
      if (data.error) error.value = data.error
      else if (data.connected) error.value = ''
    }

    const viewerHandler = (data: MinecraftViewerStatus) => {
      if (data.status === 'waiting') {
        viewerStatus.value = 'waiting'
        viewerUsername.value = data.username || ''
        error.value = ''
      } else if (data.status === 'joined') {
        viewerStatus.value = 'joined'
        if (data.username) viewerUsername.value = data.username
        error.value = ''
      } else if (data.status === 'left') {
        viewerStatus.value = 'left'
      } else if (data.status === 'error') {
        viewerStatus.value = 'error'
        if (data.username) viewerUsername.value = data.username
        error.value = data.error || 'Minecraft viewer error'
      }
    }

    const botStateHandler = (data: Record<string, unknown>) => {
      if (data.health != null) botState.value.health = data.health as number
      if (data.food != null) botState.value.food = data.food as number
      if (data.position) botState.value.position = data.position as { x: number; y: number; z: number }
      if (data.dimension) botState.value.dimension = data.dimension as string
      if (data.biome) botState.value.biome = data.biome as string
      if (data.time) botState.value.time = data.time as string
      if (data.weather) botState.value.weather = data.weather as string
      if (data.action) botState.value.action = data.action as string
      if (data.action_target) botState.value.actionTarget = data.action_target as string
      if (data.held_item) botState.value.heldItem = data.held_item as string
      if (data.inventory) botState.value.inventory = data.inventory as Array<{ name: string; count: number; slot: number }>
    }

    socket.on(Events.MINECRAFT.STATUS, statusHandler)
    socket.on(Events.MINECRAFT.VIEWER_STATUS, viewerHandler)
    socket.on(Events.MINECRAFT.BOT_STATE, botStateHandler)
    cleanup = () => {
      socket.off(Events.MINECRAFT.STATUS, statusHandler)
      socket.off(Events.MINECRAFT.VIEWER_STATUS, viewerHandler)
      socket.off(Events.MINECRAFT.BOT_STATE, botStateHandler)
    }
  }

  function teardownListener(): void {
    cleanup?.()
  }

  function start(): void {
    const socket = getSocket()
    if (!socket) return
    isConnecting.value = true
    error.value = ''
    viewerStatus.value = 'idle'
    socket.emit(Events.MINECRAFT.START, {})
  }

  function stop(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.STOP)
    viewerStatus.value = 'idle'
    viewerUsername.value = ''
  }

  function spectate(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.SPECTATE, {})
  }

  return {
    connected,
    isConnecting,
    username,
    error,
    viewerStatus,
    viewerUsername,
    botState,
    setupListener,
    teardownListener,
    start,
    stop,
    spectate,
  }
})

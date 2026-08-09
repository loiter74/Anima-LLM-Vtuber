import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import { isStageIOView, type StageIOView } from '@/types/minecraft-stage'

export interface MinecraftStatus {
  schema_version?: '1'
  generation_id?: number
  state?:
    | 'stopped'
    | 'starting_server'
    | 'probing_server'
    | 'connecting_bot'
    | 'ready'
    | 'disconnecting'
    | 'shutting_down'
    | 'error'
  mode?: 'managed' | 'external' | null
  profile?: string | null
  server?: { state?: string; owned?: boolean; host?: string | null; port?: number | null }
  bot?: { state?: string; username?: string | null }
  viewer?: MinecraftViewerStatus
  error?: string
}

export interface MinecraftViewerStatus {
  status?: 'waiting' | 'joined' | 'left' | 'error'
  state?: 'disabled' | 'waiting' | 'attached' | 'disconnected' | 'degraded'
  schema_version?: 2
  username?: string | null
  error?: string
  mode?: 'spectator'
  binding_state?: 'disabled' | 'waiting' | 'attaching' | 'following' | 'degraded'
  confirmed?: boolean
  target?: string
  attempt?: number
  retry_in_ms?: number
  reason?: string
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

type ProjectionKind =
  'mission' | 'objective' | 'proposal' | 'discovery' | 'skill_validation' | 'advancement' | 'stage'

export interface MinecraftProjectionEvent {
  schema_version: 1 | '1'
  event: string
  event_id: string
  projection_kind: ProjectionKind
  projection_version: number
  occurred_at_ms: number
  mission_id?: string
  entity_id: string
  payload: Record<string, unknown>
}

export interface MissionStatusPage {
  missions: Array<Record<string, unknown>>
  next_cursor?: string | null
}

export const useMinecraftStore = defineStore('minecraft', () => {
  const connected = ref(false)
  const isConnecting = ref(false)
  const username = ref('')
  const error = ref('')
  const lifecycleState = ref<MinecraftStatus['state']>('stopped')
  const connectionMode = ref<MinecraftStatus['mode']>(null)
  const connectionProfile = ref('')
  const serverState = ref('stopped')
  const botLifecycleState = ref('stopped')
  const serverOwned = ref(false)
  const missionProjections = ref<Record<string, Record<string, unknown>>>({})
  const objectiveProjections = ref<Record<string, Record<string, unknown>>>({})
  const proposalProjections = ref<Record<string, Record<string, unknown>>>({})
  const discoveryProjections = ref<Record<string, Record<string, unknown>>>({})
  const skillValidationProjections = ref<Record<string, Record<string, unknown>>>({})
  const advancementProjections = ref<Record<string, Record<string, unknown>>>({})
  const stageProjections = ref<Record<string, Record<string, unknown>>>({})
  const acceptedProjectionEventCount = ref(0)
  const seenProjectionEventIds = new Set<string>()
  const MAX_PROJECTION_EVENT_IDS = 10_000

  // Viewer spectator state
  const viewerStatus = ref<'idle' | 'waiting' | 'joined' | 'left' | 'error'>('idle')
  const viewerUsername = ref('')
  const viewerBindingState = ref<'disabled' | 'waiting' | 'attaching' | 'following' | 'degraded'>(
    'disabled',
  )
  const viewerConfirmed = ref(false)
  const viewerTarget = ref('')
  const viewerAttempt = ref(0)
  const viewerRetryInMs = ref<number | null>(null)
  const viewerReason = ref('')

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

  function targetProjection(kind: ProjectionKind): Record<string, Record<string, unknown>> {
    return {
      mission: missionProjections.value,
      objective: objectiveProjections.value,
      proposal: proposalProjections.value,
      discovery: discoveryProjections.value,
      skill_validation: skillValidationProjections.value,
      advancement: advancementProjections.value,
      stage: stageProjections.value,
    }[kind]
  }

  function applyProjectionEvent(data: MinecraftProjectionEvent): void {
    if (seenProjectionEventIds.has(data.event_id)) return
    const target = targetProjection(data.projection_kind)
    const currentVersion = Number(target[data.entity_id]?.projection_version ?? -1)
    if (data.projection_version < currentVersion) return
    seenProjectionEventIds.add(data.event_id)
    while (seenProjectionEventIds.size > MAX_PROJECTION_EVENT_IDS) {
      const oldest = seenProjectionEventIds.values().next().value
      if (oldest === undefined) break
      seenProjectionEventIds.delete(oldest)
    }
    target[data.entity_id] = {
      ...data.payload,
      mission_id: data.mission_id,
      projection_version: data.projection_version,
      occurred_at_ms: data.occurred_at_ms,
      event_id: data.event_id,
    }
    acceptedProjectionEventCount.value += 1
  }

  function rehydrateMissionStatus(page: MissionStatusPage): void {
    const missions: Record<string, Record<string, unknown>> = {}
    const objectives: Record<string, Record<string, unknown>> = {}
    const proposals: Record<string, Record<string, unknown>> = {}
    for (const mission of page.missions) {
      const missionId = String(mission.mission_id ?? '')
      if (!missionId) continue
      missions[missionId] = mission
      for (const objective of (mission.objectives as Array<Record<string, unknown>> | undefined) ??
        []) {
        const objectiveId = String(objective.objective_id ?? '')
        if (objectiveId) objectives[objectiveId] = { ...objective, mission_id: missionId }
      }
      for (const proposal of (mission.proposals as Array<Record<string, unknown>> | undefined) ??
        []) {
        const proposalId = String(proposal.proposal_id ?? '')
        if (proposalId) proposals[proposalId] = { ...proposal, mission_id: missionId }
      }
    }
    missionProjections.value = missions
    objectiveProjections.value = objectives
    proposalProjections.value = proposals
  }

  function walkthroughStages(missionId: string, runId?: string): StageIOView[] {
    return Object.values(stageProjections.value)
      .filter(
        (stage): stage is Record<string, unknown> & StageIOView =>
          isStageIOView(stage) &&
          stage.mission_id === missionId &&
          (runId === undefined || stage.run_id === runId),
      )
      .sort(
        (left, right) =>
          left.ordinal - right.ordinal || left.stage_id.localeCompare(right.stage_id),
      )
  }

  function setupListener(): void {
    const socket = getSocket()
    if (!socket) return

    const statusHandler = (data: MinecraftStatus) => {
      lifecycleState.value = data.state ?? 'error'
      connected.value = data.state === 'ready'
      isConnecting.value = ['starting_server', 'probing_server', 'connecting_bot'].includes(
        data.state ?? '',
      )
      connectionMode.value = data.mode ?? null
      connectionProfile.value = data.profile ?? ''
      serverState.value = data.server?.state ?? 'stopped'
      botLifecycleState.value = data.bot?.state ?? 'stopped'
      serverOwned.value = data.server?.owned === true
      if (data.bot?.username) username.value = data.bot.username
      if (data.error) error.value = data.error
      else if (data.state === 'ready' || data.state === 'stopped') error.value = ''
      if (data.viewer) viewerHandler(data.viewer)
    }

    const viewerHandler = (data: MinecraftViewerStatus) => {
      const bindingState =
        data.binding_state ??
        (
          {
            disabled: 'disabled',
            waiting: 'waiting',
            attached: 'following',
            disconnected: 'disabled',
            degraded: 'degraded',
          } as const
        )[data.state ?? 'disabled']
      viewerBindingState.value = bindingState
      if (data.confirmed !== undefined) viewerConfirmed.value = data.confirmed
      if (data.target !== undefined) viewerTarget.value = data.target
      if (data.attempt !== undefined) viewerAttempt.value = data.attempt
      if (data.retry_in_ms !== undefined) viewerRetryInMs.value = data.retry_in_ms
      if (data.reason !== undefined) viewerReason.value = data.reason
      if (!data.status) {
        viewerStatus.value = {
          disabled: 'idle',
          waiting: 'waiting',
          attaching: 'waiting',
          following: 'joined',
          degraded: 'error',
        }[bindingState] as 'idle' | 'waiting' | 'joined' | 'error'
      }
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
      if (data.position)
        botState.value.position = data.position as { x: number; y: number; z: number }
      if (data.dimension) botState.value.dimension = data.dimension as string
      if (data.biome) botState.value.biome = data.biome as string
      if (data.time) botState.value.time = data.time as string
      if (data.weather) botState.value.weather = data.weather as string
      if (data.action) botState.value.action = data.action as string
      if (data.action_target) botState.value.actionTarget = data.action_target as string
      if (data.held_item) botState.value.heldItem = data.held_item as string
      if (data.inventory)
        botState.value.inventory = data.inventory as Array<{
          name: string
          count: number
          slot: number
        }>
    }

    socket.on(Events.MINECRAFT.STATUS, statusHandler)
    socket.on(Events.MINECRAFT.VIEWER_STATUS, viewerHandler)
    socket.on(Events.MINECRAFT.BOT_STATE, botStateHandler)
    const projectionEvents = [
      Events.MINECRAFT.MISSION_PROJECTION,
      Events.MINECRAFT.OBJECTIVE_PROJECTION,
      Events.MINECRAFT.PROPOSAL_PROJECTION,
      Events.MINECRAFT.DISCOVERY_PROJECTION,
      Events.MINECRAFT.SKILL_VALIDATION,
      Events.MINECRAFT.ADVANCEMENT_PROJECTION,
      Events.MINECRAFT.STAGE_PROJECTION,
    ]
    for (const eventName of projectionEvents) socket.on(eventName, applyProjectionEvent)
    refreshStatus()
    cleanup = () => {
      socket.off(Events.MINECRAFT.STATUS, statusHandler)
      socket.off(Events.MINECRAFT.VIEWER_STATUS, viewerHandler)
      socket.off(Events.MINECRAFT.BOT_STATE, botStateHandler)
      for (const eventName of projectionEvents) socket.off(eventName, applyProjectionEvent)
    }
  }

  function teardownListener(): void {
    cleanup?.()
  }

  function requestId(operation: string): string {
    return `ui:${operation}:${crypto.randomUUID()}`
  }

  function connect(profile?: string): void {
    const socket = getSocket()
    if (!socket) return
    isConnecting.value = true
    error.value = ''
    viewerStatus.value = 'idle'
    socket.emit(Events.MINECRAFT.CONNECT, {
      request_id: requestId('connect'),
      ...(profile ? { profile } : {}),
    })
  }

  function disconnect(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.DISCONNECT, { request_id: requestId('disconnect') })
    viewerStatus.value = 'idle'
    viewerUsername.value = ''
    viewerBindingState.value = 'disabled'
    viewerConfirmed.value = false
    viewerTarget.value = ''
    viewerAttempt.value = 0
    viewerRetryInMs.value = null
    viewerReason.value = ''
  }

  function shutdown(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.SHUTDOWN, { request_id: requestId('shutdown') })
  }

  function refreshStatus(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.STATUS, { request_id: requestId('status') })
  }

  function reattachViewer(): void {
    const socket = getSocket()
    if (!socket) return
    socket.emit(Events.MINECRAFT.REATTACH_VIEWER, { request_id: requestId('reattach') })
  }

  return {
    connected,
    isConnecting,
    username,
    error,
    lifecycleState,
    connectionMode,
    connectionProfile,
    serverState,
    botLifecycleState,
    serverOwned,
    viewerStatus,
    viewerUsername,
    viewerBindingState,
    viewerConfirmed,
    viewerTarget,
    viewerAttempt,
    viewerRetryInMs,
    viewerReason,
    botState,
    missionProjections,
    objectiveProjections,
    proposalProjections,
    discoveryProjections,
    skillValidationProjections,
    advancementProjections,
    stageProjections,
    acceptedProjectionEventCount,
    walkthroughStages,
    rehydrateMissionStatus,
    setupListener,
    teardownListener,
    connect,
    disconnect,
    shutdown,
    refreshStatus,
    reattachViewer,
  }
})

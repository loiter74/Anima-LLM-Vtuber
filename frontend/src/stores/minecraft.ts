import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import { isStageIOView, type StageIOView } from '@/types/minecraft-stage'

export interface MinecraftStatus {
  connected: boolean
  username?: string
  error?: string
}

export interface MinecraftViewerStatus {
  status: 'waiting' | 'joined' | 'left' | 'error'
  schema_version?: 2
  username?: string
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
      connected.value = data.connected
      isConnecting.value = false
      if (data.username) username.value = data.username
      if (data.error) error.value = data.error
      else if (data.connected) error.value = ''
    }

    const viewerHandler = (data: MinecraftViewerStatus) => {
      if (data.binding_state) viewerBindingState.value = data.binding_state
      if (data.confirmed !== undefined) viewerConfirmed.value = data.confirmed
      if (data.target !== undefined) viewerTarget.value = data.target
      if (data.attempt !== undefined) viewerAttempt.value = data.attempt
      if (data.retry_in_ms !== undefined) viewerRetryInMs.value = data.retry_in_ms
      if (data.reason !== undefined) viewerReason.value = data.reason
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
    viewerBindingState.value = 'disabled'
    viewerConfirmed.value = false
    viewerTarget.value = ''
    viewerAttempt.value = 0
    viewerRetryInMs.value = null
    viewerReason.value = ''
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
    start,
    stop,
    spectate,
  }
})

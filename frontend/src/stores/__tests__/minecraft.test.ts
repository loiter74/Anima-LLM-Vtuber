import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMinecraftStore } from '@/stores/minecraft'
import { Events } from '@/constants/socket-events'

const socket = {
  on: vi.fn(),
  off: vi.fn(),
  emit: vi.fn(),
}

vi.mock('@/services/socket', () => ({
  getSocket: () => socket,
}))

describe('useMinecraftStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    socket.on.mockReset()
    socket.off.mockReset()
    socket.emit.mockReset()
  })

  function registeredHandler(eventName: string) {
    return socket.on.mock.calls.find(([event]) => event === eventName)?.[1]
  }

  it('updates viewer status and error from minecraft:viewer_status errors', () => {
    const store = useMinecraftStore()
    store.setupListener()

    const viewerHandler = registeredHandler(Events.MINECRAFT.VIEWER_STATUS)
    viewerHandler?.({ status: 'waiting', username: 'viewer' })
    viewerHandler?.({ status: 'error', error: 'Bot not running' })

    expect(store.viewerStatus).toBe('error')
    expect(store.viewerUsername).toBe('viewer')
    expect(store.error).toBe('Bot not running')
  })

  it('preserves the V2 binding status while projecting legacy status', () => {
    const store = useMinecraftStore()
    store.setupListener()

    const viewerHandler = registeredHandler(Events.MINECRAFT.VIEWER_STATUS)
    viewerHandler?.({
      schema_version: 2,
      status: 'joined',
      binding_state: 'following',
      confirmed: true,
      username: 'LUN077',
      target: 'AnimettaBot',
      attempt: 2,
      retry_in_ms: 0,
      reason: 'viewer_joined',
    })

    expect(store.viewerStatus).toBe('joined')
    expect(store.viewerBindingState).toBe('following')
    expect(store.viewerConfirmed).toBe(true)
    expect(store.viewerTarget).toBe('AnimettaBot')
    expect(store.viewerAttempt).toBe(2)
    expect(store.viewerRetryInMs).toBe(0)
    expect(store.viewerReason).toBe('viewer_joined')
  })

  it('emits minecraft control events', () => {
    const store = useMinecraftStore()

    store.connect()
    store.reattachViewer()
    store.disconnect()
    store.shutdown()
    store.refreshStatus()

    expect(socket.emit).toHaveBeenCalledWith(
      Events.MINECRAFT.CONNECT,
      expect.objectContaining({ request_id: expect.stringContaining('ui:connect:') }),
    )
    expect(socket.emit).toHaveBeenCalledWith(
      Events.MINECRAFT.REATTACH_VIEWER,
      expect.objectContaining({ request_id: expect.stringContaining('ui:reattach:') }),
    )
    expect(socket.emit).toHaveBeenCalledWith(
      Events.MINECRAFT.DISCONNECT,
      expect.objectContaining({ request_id: expect.stringContaining('ui:disconnect:') }),
    )
    expect(socket.emit).toHaveBeenCalledWith(
      Events.MINECRAFT.SHUTDOWN,
      expect.objectContaining({ request_id: expect.stringContaining('ui:shutdown:') }),
    )
  })

  it('projects server bot and viewer lifecycle layers', () => {
    const store = useMinecraftStore()
    store.setupListener()
    const statusHandler = registeredHandler(Events.MINECRAFT.STATUS)

    statusHandler?.({
      state: 'ready',
      mode: 'managed',
      profile: 'managed-local',
      server: { state: 'available', owned: true },
      bot: { state: 'ready', username: 'AnimettaBot' },
      viewer: {
        state: 'attached',
        confirmed: true,
        username: 'LUN077',
      },
    })

    expect(store.serverState).toBe('available')
    expect(store.botLifecycleState).toBe('ready')
    expect(store.viewerStatus).toBe('joined')
    expect(store.viewerBindingState).toBe('following')
  })

  it('deduplicates mission-domain projections and rejects stale versions', () => {
    const store = useMinecraftStore()
    store.setupListener()
    const missionHandler = registeredHandler(Events.MINECRAFT.MISSION_PROJECTION)
    const event = {
      schema_version: 1,
      event: 'minecraft.mission.projection',
      event_id: 'mission-1:mission:2',
      projection_kind: 'mission',
      projection_version: 2,
      occurred_at_ms: 100,
      mission_id: 'mission-1',
      entity_id: 'mission-1',
      payload: { mission_id: 'mission-1', status: 'running' },
    }

    missionHandler?.(event)
    missionHandler?.({ ...event, payload: { mission_id: 'mission-1', status: 'failed' } })
    missionHandler?.({
      ...event,
      event_id: 'mission-1:mission:1',
      projection_version: 1,
      payload: { mission_id: 'mission-1', status: 'accepted' },
    })

    expect(store.missionProjections['mission-1']?.status).toBe('running')
    expect(store.acceptedProjectionEventCount).toBe(1)
  })

  it('rehydrates mission objective and proposal state from progress projection', () => {
    const store = useMinecraftStore()

    store.rehydrateMissionStatus({
      missions: [
        {
          mission_id: 'mission-1',
          projection_version: 7,
          status: 'running',
          objectives: [
            { objective_id: 'fight-zombie', readiness: 'active', command_phase: 'running' },
          ],
          proposals: [{ proposal_id: 'proposal-1', outcome: 'accepted', reason_code: 'ADMITTED' }],
        },
      ],
      next_cursor: null,
    })

    expect(store.missionProjections['mission-1']?.projection_version).toBe(7)
    expect(store.objectiveProjections['fight-zombie']?.readiness).toBe('active')
    expect(store.proposalProjections['proposal-1']?.outcome).toBe('accepted')
  })

  it('projects StageIO v2 into an ordinal walkthrough for one run and mission', () => {
    const store = useMinecraftStore()
    store.setupListener()
    const stageHandler = registeredHandler(Events.MINECRAFT.STAGE_PROJECTION)
    const stage = {
      schema_version: '2',
      run_id: 'run-1',
      mission_id: 'mission-1',
      stage_id: 'combat',
      ordinal: 5,
      gameplay_evidence_eligible: true,
      lifecycle: 'running',
      input_refs: [],
      output_refs: [],
      state_deltas: [],
      predicates: [],
      checkpoints: [],
      evidence_refs: [],
      media: [],
    }

    stageHandler?.({
      schema_version: 1,
      event: 'minecraft.stage.projection',
      event_id: 'run-1:mission-1:combat:1',
      projection_kind: 'stage',
      projection_version: 1,
      occurred_at_ms: 100,
      mission_id: 'mission-1',
      entity_id: 'run-1:mission-1:combat',
      payload: stage,
    })

    expect(store.walkthroughStages('mission-1', 'run-1')).toEqual([
      expect.objectContaining({ stage_id: 'combat', ordinal: 5, lifecycle: 'running' }),
    ])
    expect(store.walkthroughStages('mission-2', 'run-1')).toEqual([])
  })
})

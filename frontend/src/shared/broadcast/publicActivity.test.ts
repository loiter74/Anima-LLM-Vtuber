import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Events } from '@/constants/socket-events'
import type { LiveSocket } from '@/shared/transport/liveSocket'
import {
  createPublicMediaOwnership,
  resolvePublicMediaMode,
  type PublicMediaLock,
  type PublicMediaLockManager,
} from './mediaOwnership'
import {
  createPublicActivityController,
  parseLivestreamNarrationState,
  parseMinecraftActivityProjection,
  publicActivityVisualText,
  type PublicActivityView,
} from './publicActivity'
import { createDomPublicActivityView } from './publicActivityView'

function activity(version: number, eventId = `activity:${version}`) {
  return {
    schema_version: '1',
    event: 'minecraft.activity.projection',
    event_id: eventId,
    projection_kind: 'activity',
    projection_version: version,
    occurred_at_ms: version * 100,
    mission_id: 'mission-1',
    entity_id: 'minecraft',
    payload: {
      phase: version === 3 ? 'finished' : 'acting',
      intent: version === 1 ? 'acquire' : undefined,
      focus: { kind: 'item', label: '铁矿' },
      progress: { current: version, total: 3, unit: 'actions' },
      outcome: version === 3 ? 'succeeded' : 'active',
    },
    ignored_future_field: { safe: true },
  }
}

function narration(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: '1',
    cue_id: 'cue:1',
    source_event_id: 'activity:1',
    task_id: 'task-1',
    phase: 'acting',
    visual_text: '我先沿着这条矿道找找看。',
    emotion: 'focused',
    speech_state: 'queued',
    occurred_at_ms: 100,
    ...overrides,
  }
}

function controllerHarness(maxActivities = 12, onVisualCue = vi.fn()) {
  const handlers = new Map<string, (...args: unknown[]) => void>()
  const socket: LiveSocket = {
    on: vi.fn((event, handler) => {
      handlers.set(event, handler)
      return socket
    }),
    off: vi.fn((event, handler) => {
      if (handlers.get(event) === handler) handlers.delete(event)
      return socket
    }),
  }
  const view = {
    renderPublicActivities: vi.fn(),
    setPublicNarration: vi.fn(),
  } satisfies PublicActivityView
  const controller = createPublicActivityController(socket, view, { maxActivities, onVisualCue })
  return { controller, handlers, onVisualCue, socket, view }
}

class FakeLockManager implements PublicMediaLockManager {
  private readonly held = new Set<string>()

  async request(
    name: string,
    _options: { mode: 'exclusive'; ifAvailable: true },
    callback: (lock: PublicMediaLock | null) => Promise<void> | void,
  ): Promise<void> {
    if (this.held.has(name)) {
      await callback(null)
      return
    }
    this.held.add(name)
    try {
      await callback({ name })
    } finally {
      this.held.delete(name)
    }
  }
}

describe('public broadcast activity', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    localStorage.clear()
  })

  it('parses only the bounded public contract while ignoring future fields', () => {
    const parsed = parseMinecraftActivityProjection(activity(1))

    expect(parsed).toEqual({
      schema_version: '1',
      event: 'minecraft.activity.projection',
      event_id: 'activity:1',
      projection_kind: 'activity',
      projection_version: 1,
      occurred_at_ms: 100,
      mission_id: 'mission-1',
      entity_id: 'minecraft',
      payload: {
        phase: 'acting',
        intent: 'acquire',
        focus: { kind: 'item', label: '铁矿' },
        progress: { current: 1, total: 3, unit: 'actions' },
        outcome: 'active',
      },
    })
    expect(parseMinecraftActivityProjection({ ...activity(1), schema_version: '2' })).toBeNull()
    expect(
      parseMinecraftActivityProjection({
        ...activity(1),
        payload: { ...activity(1).payload, outcome: 'secret_internal_state' },
      }),
    ).toBeNull()
    expect(parseMinecraftActivityProjection({ ...activity(1), projection_version: 2 })).toBeNull()
    expect(
      parseMinecraftActivityProjection({
        ...activity(1),
        mission_id: null,
        payload: {
          phase: 'planning',
          intent: null,
          focus: null,
          progress: null,
          outcome: 'active',
        },
      }),
    ).toEqual(
      expect.objectContaining({
        event_id: 'activity:1',
        payload: { phase: 'planning', outcome: 'active' },
      }),
    )
    expect(
      parseMinecraftActivityProjection({
        ...activity(1),
        payload: {
          ...activity(1).payload,
          focus: { kind: 'block', label: '铁矿' },
        },
      }),
    ).toBeNull()
    expect(
      parseMinecraftActivityProjection({
        ...activity(1),
        payload: {
          ...activity(1).payload,
          focus: { kind: 'item', label: '铁'.repeat(65) },
        },
      }),
    ).toBeNull()
  })

  it('derives deterministic public copy without interpreting internal reasoning', () => {
    const parsed = parseMinecraftActivityProjection(activity(3))!

    expect(publicActivityVisualText(parsed)).toBe('结果 · 铁矿 · 3/3 步 · 已完成')
    expect(publicActivityVisualText(parsed)).not.toContain('reasoning')
  })

  it('orders out-of-order projections, deduplicates event ids, and bounds the buffer', () => {
    const { controller, handlers, view } = controllerHarness(2)
    const onActivity = handlers.get(Events.MINECRAFT.ACTIVITY_PROJECTION)!

    onActivity(activity(2))
    onActivity(activity(1))
    onActivity(activity(2, 'activity:2'))
    onActivity(activity(3))

    expect(controller.activities.map((item) => item.projection_version)).toEqual([2, 3])
    expect(view.renderPublicActivities).toHaveBeenLastCalledWith([
      expect.objectContaining({ event_id: 'activity:2' }),
      expect.objectContaining({ event_id: 'activity:3' }),
    ])
    controller.dispose()
    expect(handlers.size).toBe(0)
  })

  it('keeps the newest narration state and accepts state transitions for one cue', () => {
    const { controller, handlers, view } = controllerHarness()
    const onNarration = handlers.get(Events.LIVESTREAM.NARRATION_STATE)!

    onNarration(narration({ speech_state: 'speaking', occurred_at_ms: 200 }))
    onNarration(narration({ speech_state: 'queued', occurred_at_ms: 100 }))
    onNarration(narration({ speech_state: 'completed', occurred_at_ms: 300 }))
    onNarration(narration({ speech_state: 'queued', occurred_at_ms: 300 }))
    onNarration(narration({ speech_state: 'completed', occurred_at_ms: 400 }))

    expect(controller.narration).toEqual(
      expect.objectContaining({ speech_state: 'completed', occurred_at_ms: 300 }),
    )
    expect(view.setPublicNarration).toHaveBeenCalledTimes(2)
    expect(parseLivestreamNarrationState({ ...narration(), visual_text: '' })).toBeNull()
    expect(parseLivestreamNarrationState({ ...narration(), speech_state: 'internal' })).toBeNull()
    controller.dispose()
  })

  it('orders different narration cues by source activity sequence within one millisecond', () => {
    const { controller, handlers } = controllerHarness()
    const onNarration = handlers.get(Events.LIVESTREAM.NARRATION_STATE)!

    onNarration(narration({ cue_id: 'cue:z', source_event_id: 'activity:10', occurred_at_ms: 100 }))
    onNarration(narration({ cue_id: 'cue:a', source_event_id: 'activity:11', occurred_at_ms: 100 }))
    onNarration(narration({ cue_id: 'cue:zz', source_event_id: 'activity:9', occurred_at_ms: 100 }))

    expect(controller.narration).toEqual(
      expect.objectContaining({ cue_id: 'cue:a', source_event_id: 'activity:11' }),
    )
    controller.dispose()
  })

  it.each([
    ['completed', 'cancelled'],
    ['cancelled', 'completed'],
  ] as const)('keeps the first %s terminal state when %s arrives later', (first, later) => {
    const { controller, handlers } = controllerHarness()
    const onNarration = handlers.get(Events.LIVESTREAM.NARRATION_STATE)!

    onNarration(narration({ speech_state: first }))
    onNarration(narration({ speech_state: later }))

    expect(controller.narration?.speech_state).toBe(first)
    controller.dispose()
  })

  it('emits one sanitized Live2D cue per source activity without depending on speech', () => {
    const { controller, handlers, onVisualCue } = controllerHarness()
    const onNarration = handlers.get(Events.LIVESTREAM.NARRATION_STATE)!

    onNarration(narration({ speech_state: 'none', emotion: 'focused' }))
    onNarration(narration({ speech_state: 'queued', emotion: 'focused' }))

    expect(onVisualCue).toHaveBeenCalledOnce()
    expect(onVisualCue).toHaveBeenCalledWith({
      sourceEventId: 'activity:1',
      phase: 'acting',
      emotion: 'focused',
    })
    controller.dispose()
  })

  it('renders ordered activity and narration with textContent and persistent identities', () => {
    document.body.innerHTML = `
      <aside id="publicActivityPanel" hidden>
        <section id="publicNarrationState" hidden></section>
        <span id="publicCurrentIntent"></span>
        <span id="publicRecentObservation"></span>
        <span id="publicNextPhase"></span>
        <ol id="publicActivityList"></ol>
      </aside>
    `
    const view = createDomPublicActivityView(document)
    const first = parseMinecraftActivityProjection(activity(1))!
    const second = parseMinecraftActivityProjection(activity(2))!
    view.renderPublicActivities([
      { ...first, phaseLabel: '执行', visualText: '执行 · 第一步' },
      { ...second, phaseLabel: '检查', visualText: '<检查完成>' },
    ])
    view.setPublicNarration(parseLivestreamNarrationState(narration())!)

    const items = document.querySelectorAll<HTMLElement>('.public-activity-item')
    expect([...items].map((item) => item.dataset.eventId)).toEqual(['activity:1', 'activity:2'])
    expect(items[1].textContent).toContain('<检查完成>')
    expect(items[1].querySelector('检查完成')).toBeNull()
    const narrationElement = document.getElementById('publicNarrationState')!
    expect(narrationElement.dataset.taskId).toBe('task-1')
    expect(narrationElement.dataset.sourceEventId).toBe('activity:1')
    expect(document.getElementById('publicActivityPanel')?.hidden).toBe(false)
  })

  it('resolves explicit media ownership with surface-specific defaults', () => {
    expect(resolvePublicMediaMode(new URLSearchParams(), 'active')).toBe('active')
    expect(resolvePublicMediaMode(new URLSearchParams(), 'muted')).toBe('muted')
    expect(resolvePublicMediaMode(new URLSearchParams('media=active'), 'muted')).toBe('active')
    expect(resolvePublicMediaMode(new URLSearchParams('media=muted'), 'active')).toBe('muted')
    expect(resolvePublicMediaMode(new URLSearchParams('media=loud'), 'muted')).toBe('muted')
  })

  it('uses one atomic lock and lets a delayed contender take over after release', async () => {
    const lockManager = new FakeLockManager()
    const live = createPublicMediaOwnership(new URLSearchParams('media=active'), 'active', {
      ownerId: 'live-page',
      lockManager,
      retryMs: 5,
    })
    const gameplay = createPublicMediaOwnership(new URLSearchParams('media=active'), 'muted', {
      ownerId: 'gameplay-page',
      lockManager,
      retryMs: 5,
    })

    expect(await live.acquirePlayback()).toEqual({ ownerId: 'live-page', fence: 1 })
    expect(live.snapshot.state).toBe('active')
    expect(await gameplay.acquirePlayback()).toBeNull()
    expect(gameplay.snapshot.state).toBe('standby')

    live.dispose()
    await vi.waitFor(() => expect(gameplay.canPlay()).toBe(true))
    expect(gameplay.snapshot).toEqual(
      expect.objectContaining({ state: 'active', ownerId: 'gameplay-page', fence: 1 }),
    )
    gameplay.dispose()
  })

  it('fails closed when the browser has no Web Locks implementation', async () => {
    const ownership = createPublicMediaOwnership(new URLSearchParams('media=active'), 'active', {
      ownerId: 'unsupported-page',
      lockManager: null,
    })

    expect(ownership.snapshot.state).toBe('standby')
    expect(ownership.canPlay()).toBe(false)
    expect(await ownership.acquirePlayback()).toBeNull()
    ownership.dispose()
  })
})

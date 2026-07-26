import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LiveView } from '../controller'
import { bootstrapLiveSession } from '../bootstrap'
import type { LiveSocketRuntime } from '../socket-runtime'

function viewHarness(): LiveView {
  return {
    renderMessages: vi.fn(),
    setSocketState: vi.fn(),
    setLivestreamStatus: vi.fn(),
    setBackground: vi.fn(),
  }
}

function startSession(session: object): void {
  expect(session).toHaveProperty('start', expect.any(Function))
  if ('start' in session && typeof session.start === 'function') session.start()
}

describe('standalone live bootstrap', () => {
  afterEach(() => vi.useRealTimers())

  it('starts the baseline review source after controller listeners are registered', () => {
    vi.useFakeTimers()
    const view = viewHarness()
    const createNetworkRuntime = vi.fn<() => LiveSocketRuntime>()

    const session = bootstrapLiveSession({
      search: new URLSearchParams('review=1&scene=baseline'),
      view,
      createNetworkRuntime,
    })

    expect(view.renderMessages).not.toHaveBeenCalled()
    startSession(session)
    vi.runAllTimers()

    expect(createNetworkRuntime).not.toHaveBeenCalled()
    expect(session.mode).toBe('review')
    expect(view.setSocketState).toHaveBeenLastCalledWith('connected')
    expect(view.setLivestreamStatus).toHaveBeenLastCalledWith(
      expect.objectContaining({ state: 'live', connected: true }),
    )
    expect(view.renderMessages).toHaveBeenCalledTimes(2)
    expect(view.renderMessages).toHaveBeenLastCalledWith([
      expect.objectContaining({ user_name: '星野' }),
      expect.objectContaining({ user_name: '小雨' }),
    ])

    session.dispose()
  })

  it('maps demo=1 through the same private baseline path', () => {
    vi.useFakeTimers()
    const view = viewHarness()
    const createNetworkRuntime = vi.fn<() => LiveSocketRuntime>()

    const session = bootstrapLiveSession({
      search: new URLSearchParams('demo=1'),
      view,
      createNetworkRuntime,
    })
    startSession(session)
    vi.runAllTimers()

    expect(createNetworkRuntime).not.toHaveBeenCalled()
    expect(view.renderMessages).toHaveBeenCalledTimes(2)

    session.dispose()
  })

  it('disposes the controller and runtime exactly once', () => {
    const view = viewHarness()
    const socket = {
      on: vi.fn(),
      off: vi.fn(),
    }
    socket.on.mockReturnValue(socket)
    socket.off.mockReturnValue(socket)
    const runtime = {
      mode: 'network' as const,
      socket,
      start: vi.fn(),
      dispose: vi.fn(),
    }

    const session = bootstrapLiveSession({
      search: new URLSearchParams(),
      view,
      createNetworkRuntime: () => runtime,
    })
    startSession(session)
    startSession(session)

    session.dispose()
    session.dispose()

    expect(runtime.start).toHaveBeenCalledOnce()
    expect(runtime.dispose).toHaveBeenCalledOnce()
  })
})

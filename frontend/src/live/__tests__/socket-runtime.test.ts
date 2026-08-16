import { describe, expect, it, vi } from 'vitest'
import type { LiveSocket } from '../controller'
import { createLiveSocketRuntime, type LiveSocketRuntime } from '../socket-runtime'

function networkRuntime(): LiveSocketRuntime {
  const socket: LiveSocket = {
    on: vi.fn(() => socket),
    off: vi.fn(() => socket),
  }
  return {
    mode: 'network',
    socket,
    start: vi.fn(),
    dispose: vi.fn(),
  }
}

describe('live socket runtime selection', () => {
  it('does not construct the network or pairing client for review mode', () => {
    const createNetworkRuntime = vi.fn(networkRuntime)

    const runtime = createLiveSocketRuntime(
      new URLSearchParams('review=1&scene=empty&pair=1'),
      createNetworkRuntime,
    )

    expect(runtime.mode).toBe('review')
    expect(createNetworkRuntime).not.toHaveBeenCalled()
  })

  it('does not construct the network client for legacy demo mode', () => {
    const createNetworkRuntime = vi.fn(networkRuntime)

    const runtime = createLiveSocketRuntime(new URLSearchParams('demo=1'), createNetworkRuntime)

    expect(runtime.mode).toBe('review')
    expect(createNetworkRuntime).not.toHaveBeenCalled()
  })

  it('uses the network runtime for the production page', () => {
    const expected = networkRuntime()
    const createNetworkRuntime = vi.fn(() => expected)

    const runtime = createLiveSocketRuntime(new URLSearchParams(), createNetworkRuntime)

    expect(runtime).toBe(expected)
    expect(createNetworkRuntime).toHaveBeenCalledOnce()
  })
})

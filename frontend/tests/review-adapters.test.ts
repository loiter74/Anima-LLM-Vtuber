// @vitest-environment node

import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'
import { PNG } from 'pngjs'
import { describe, expect, it, vi } from 'vitest'
import { ObsPreviewAdapter, type ObsClient } from '../scripts/review/obs'
import { ServerLease } from '../scripts/review/server-lease'
import * as serverLeaseModule from '../scripts/review/server-lease'

function childProcessHarness() {
  const child = new EventEmitter() as EventEmitter & {
    pid: number
    stdout: PassThrough
    stderr: PassThrough
  }
  child.pid = 42
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  return child
}

describe('ServerLease', () => {
  it('launches pnpm through cmd.exe on Windows instead of spawning a cmd shim directly', () => {
    const createViteSpawnSpec = (
      serverLeaseModule as unknown as {
        createViteSpawnSpec?: (
          platform: NodeJS.Platform,
          commandShell?: string,
        ) => { command: string; args: string[] }
      }
    ).createViteSpawnSpec

    expect(createViteSpawnSpec).toBeTypeOf('function')
    if (!createViteSpawnSpec) return
    expect(createViteSpawnSpec('win32', 'C:\\Windows\\System32\\cmd.exe')).toEqual({
      command: 'C:\\Windows\\System32\\cmd.exe',
      args: ['/d', '/s', '/c', 'pnpm dev --host 127.0.0.1'],
    })
    expect(createViteSpawnSpec('linux')).toEqual({
      command: 'pnpm',
      args: ['dev', '--host', '127.0.0.1'],
    })
  })

  it('reuses a healthy external server without taking ownership', async () => {
    const spawnServer = vi.fn()
    const terminate = vi.fn()
    const lease = await ServerLease.acquire({
      baseUrl: 'http://127.0.0.1:3000',
      probe: vi.fn().mockResolvedValue(true),
      spawnServer,
      terminate,
    })

    expect(lease.owned).toBe(false)
    expect(spawnServer).not.toHaveBeenCalled()
    await lease.dispose()
    expect(terminate).not.toHaveBeenCalled()
  })

  it('terminates an owned server exactly once', async () => {
    const child = childProcessHarness()
    const probe = vi
      .fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true)
    const terminate = vi.fn().mockResolvedValue(undefined)
    const lease = await ServerLease.acquire({
      baseUrl: 'http://127.0.0.1:3000',
      probe,
      spawnServer: () => child as never,
      terminate,
      wait: async () => undefined,
      attempts: 3,
    })

    expect(lease.owned).toBe(true)
    await lease.dispose()
    await lease.dispose()
    expect(terminate).toHaveBeenCalledOnce()
    expect(terminate).toHaveBeenCalledWith(child)
  })

  it('preserves bounded startup logs when an owned server never becomes ready', async () => {
    const child = childProcessHarness()
    const terminate = vi.fn().mockResolvedValue(undefined)
    const acquiring = ServerLease.acquire({
      baseUrl: 'http://127.0.0.1:3000',
      probe: vi.fn().mockResolvedValue(false),
      spawnServer: () => {
        queueMicrotask(() => child.stderr.write('vite failed to bind'))
        return child as never
      },
      terminate,
      wait: async () => undefined,
      attempts: 2,
    })

    await expect(acquiring).rejects.toThrow(/vite failed to bind/)
    expect(terminate).toHaveBeenCalledWith(child)
  })
})

function obsHarness(overrides: Record<string, Record<string, unknown>> = {}, failOnce?: string) {
  const calls: Array<[string, Record<string, unknown> | undefined]> = []
  const image = new PNG({ width: 1080, height: 1920 })
  image.data.fill(255)
  const responses: Record<string, Record<string, unknown>> = {
    GetStreamStatus: { outputActive: false },
    GetRecordStatus: { outputActive: false },
    GetCurrentProgramScene: { currentProgramSceneName: 'Original' },
    GetSceneList: { scenes: [{ sceneName: 'Original' }] },
    GetInputList: { inputs: [] },
    GetInputSettings: { inputSettings: { url: 'about:blank', reroute_audio: false } },
    GetInputAudioMonitorType: { monitorType: 'OBS_MONITORING_TYPE_NONE' },
    GetSourceScreenshot: {
      imageData: `data:image/png;base64,${PNG.sync.write(image).toString('base64')}`,
    },
    ...overrides,
  }
  const client: ObsClient = {
    connect: vi.fn().mockResolvedValue({}),
    call: vi.fn(async (requestType, requestData) => {
      calls.push([requestType, requestData])
      if (requestType === failOnce) {
        failOnce = undefined
        throw new Error('injected OBS failure')
      }
      return responses[requestType] ?? {}
    }),
    disconnect: vi.fn().mockResolvedValue(undefined),
  }
  return { client, calls }
}

describe('OBS preview adapter', () => {
  const options = {
    url: 'ws://127.0.0.1:4455',
    password: 'secret',
    sceneName: 'Animetta Review',
    sourceName: 'Animetta Live Browser',
    width: 1080,
    height: 1920,
  }

  it('creates a dedicated browser source, updates it, captures PNG, and restores the scene', async () => {
    const { client, calls } = obsHarness()
    const adapter = new ObsPreviewAdapter(client, options)

    await adapter.prepare()
    await adapter.updateSource('http://127.0.0.1:3000/live.html?review=1&scene=empty')
    const screenshot = await adapter.capture()
    await adapter.dispose()

    expect(client.connect).toHaveBeenCalledWith(options.url, 'secret', { rpcVersion: 1 })
    expect(calls).toContainEqual(['CreateScene', { sceneName: options.sceneName }])
    expect(calls).toContainEqual([
      'CreateInput',
      expect.objectContaining({
        sceneName: options.sceneName,
        inputName: options.sourceName,
        inputKind: 'browser_source',
      }),
    ])
    expect(calls).toContainEqual([
      'SetInputSettings',
      expect.objectContaining({
        inputName: options.sourceName,
        overlay: true,
        inputSettings: expect.objectContaining({
          url: 'http://127.0.0.1:3000/live.html?review=1&scene=empty',
          width: 1080,
          height: 1920,
        }),
      }),
    ])
    expect(PNG.sync.read(screenshot)).toEqual(
      expect.objectContaining({ width: 1080, height: 1920 }),
    )
    expect(calls.slice(-3)).toEqual([
      ['SetCurrentProgramScene', { sceneName: 'Original' }],
      ['RemoveInput', { inputName: options.sourceName }],
      ['RemoveScene', { sceneName: options.sceneName }],
    ])
    expect(client.disconnect).toHaveBeenCalledOnce()
  })

  it('refuses to modify OBS while streaming or recording', async () => {
    const { client, calls } = obsHarness({
      GetStreamStatus: { outputActive: true },
    })
    const adapter = new ObsPreviewAdapter(client, options)

    await expect(adapter.prepare()).rejects.toThrow(/streaming or recording/)
    expect(calls.some(([request]) => request === 'CreateScene')).toBe(false)
    expect(client.disconnect).toHaveBeenCalledOnce()
  })

  it('temporarily enables browser audio and restores existing source settings and monitoring', async () => {
    const { client, calls } = obsHarness({
      GetSceneList: { scenes: [{ sceneName: 'Original' }, { sceneName: options.sceneName }] },
      GetInputList: {
        inputs: [{ inputName: options.sourceName, inputKind: 'browser_source' }],
      },
      GetInputSettings: {
        inputSettings: {
          url: 'https://example.invalid/previous',
          width: 640,
          height: 360,
          reroute_audio: false,
        },
      },
      GetInputAudioMonitorType: { monitorType: 'OBS_MONITORING_TYPE_NONE' },
    })
    const adapter = new ObsPreviewAdapter(client, {
      ...options,
      enableAudioMonitoring: true,
    })

    await adapter.prepare()
    await adapter.updateSource('http://127.0.0.1:3000/tts-failover.html')
    await adapter.dispose()

    expect(calls).toContainEqual([
      'SetInputSettings',
      {
        inputName: options.sourceName,
        inputSettings: { reroute_audio: true },
        overlay: true,
      },
    ])
    expect(calls).toContainEqual([
      'SetInputAudioMonitorType',
      {
        inputName: options.sourceName,
        monitorType: 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT',
      },
    ])
    expect(calls).toContainEqual([
      'SetInputSettings',
      {
        inputName: options.sourceName,
        inputSettings: {
          url: 'https://example.invalid/previous',
          width: 640,
          height: 360,
          reroute_audio: false,
        },
        overlay: false,
      },
    ])
    expect(calls).toContainEqual([
      'SetInputAudioMonitorType',
      {
        inputName: options.sourceName,
        monitorType: 'OBS_MONITORING_TYPE_NONE',
      },
    ])
    expect(calls.at(-1)).toEqual(['SetCurrentProgramScene', { sceneName: 'Original' }])
  })

  it('restores audio settings when preparation fails after changing the source', async () => {
    const { client, calls } = obsHarness(
      {
        GetInputList: {
          inputs: [{ inputName: options.sourceName, inputKind: 'browser_source' }],
        },
        GetInputSettings: {
          inputSettings: { url: 'about:blank', reroute_audio: false },
        },
        GetInputAudioMonitorType: { monitorType: 'OBS_MONITORING_TYPE_NONE' },
      },
      'SetCurrentProgramScene',
    )
    const adapter = new ObsPreviewAdapter(client, {
      ...options,
      enableAudioMonitoring: true,
    })

    await expect(adapter.prepare()).rejects.toThrow('injected OBS failure')

    expect(calls).toContainEqual([
      'SetInputSettings',
      {
        inputName: options.sourceName,
        inputSettings: { url: 'about:blank', reroute_audio: false },
        overlay: false,
      },
    ])
    expect(calls).toContainEqual([
      'SetInputAudioMonitorType',
      {
        inputName: options.sourceName,
        monitorType: 'OBS_MONITORING_TYPE_NONE',
      },
    ])
    expect(client.disconnect).toHaveBeenCalledOnce()
  })

  it('removes a newly created source and scene when preparation fails', async () => {
    const { client, calls } = obsHarness({}, 'SetCurrentProgramScene')
    const adapter = new ObsPreviewAdapter(client, {
      ...options,
      enableAudioMonitoring: true,
    })

    await expect(adapter.prepare()).rejects.toThrow('injected OBS failure')

    expect(calls).toContainEqual(['RemoveInput', { inputName: options.sourceName }])
    expect(calls).toContainEqual(['RemoveScene', { sceneName: options.sceneName }])
    expect(client.disconnect).toHaveBeenCalledOnce()
  })
})

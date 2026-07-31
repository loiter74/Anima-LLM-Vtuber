// @vitest-environment node

import { PNG } from 'pngjs'
import { describe, expect, it, vi } from 'vitest'
import {
  analyzeMinecraftFrames,
  MinecraftObsCompositeAdapter,
  selectMinecraftWindow,
} from '../scripts/review/minecraft-obs'
import type { ObsClient } from '../scripts/review/obs'

function harness(failOnce?: string) {
  const calls: Array<[string, Record<string, unknown> | undefined]> = []
  const image = new PNG({ width: 1920, height: 1080 })
  image.data.fill(180)
  let screenshotCount = 0
  const client: ObsClient = {
    connect: vi.fn().mockResolvedValue({}),
    disconnect: vi.fn().mockResolvedValue(undefined),
    call: vi.fn(async (requestType, requestData) => {
      calls.push([requestType, requestData])
      if (requestType === failOnce) {
        failOnce = undefined
        throw new Error('injected composite failure')
      }
      if (requestType === 'GetStreamStatus' || requestType === 'GetRecordStatus') {
        return { outputActive: false }
      }
      if (requestType === 'GetCurrentProgramScene') {
        return { currentProgramSceneName: 'Original' }
      }
      if (requestType === 'GetVideoSettings') {
        return {
          baseWidth: 1080,
          baseHeight: 1920,
          outputWidth: 1080,
          outputHeight: 1920,
          fpsNumerator: 60,
          fpsDenominator: 1,
        }
      }
      if (requestType === 'GetSceneList') return { scenes: [{ sceneName: 'Original' }] }
      if (requestType === 'GetInputList') return { inputs: [] }
      if (requestType === 'CreateInput') {
        const inputName = String(requestData?.inputName ?? '')
        return {
          sceneItemId: inputName.includes('Game Audio')
            ? 12
            : inputName.includes('Game Capture')
              ? 11
              : 13,
        }
      }
      if (requestType === 'GetInputPropertiesListPropertyItems') {
        return {
          propertyItems: [
            {
              itemName: 'Minecraft 1.21',
              itemValue: 'Minecraft 1.21:GLFW30:javaw.exe',
              itemEnabled: true,
            },
          ],
        }
      }
      if (requestType === 'GetSourceFilterList') return { filters: [] }
      if (requestType === 'GetSourceScreenshot') {
        screenshotCount += 1
        if (screenshotCount > 1) {
          for (let y = 200; y < 260; y += 1) {
            for (let x = 300; x < 360; x += 1) {
              const offset = (y * image.width + x) * 4
              image.data[offset] = 30
            }
          }
        }
        return {
          imageData: `data:image/png;base64,${PNG.sync.write(image).toString('base64')}`,
        }
      }
      return {}
    }),
  }
  return { client, calls }
}

const options = {
  url: 'ws://127.0.0.1:4455',
  password: 'secret',
  sceneName: 'Animetta Minecraft Review',
  sourceName: 'Animetta Minecraft Overlay',
  gameSourceName: 'Animetta Minecraft Game Capture',
  gameAudioSourceName: 'Animetta Minecraft Game Audio',
  duckingFilterName: 'Animetta TTS Sidechain',
  width: 1920,
  height: 1080,
  frameDelayMs: 0,
}

describe('selectMinecraftWindow', () => {
  it('requires exactly one enabled javaw candidate', () => {
    expect(
      selectMinecraftWindow([
        { itemName: 'OBS', itemValue: 'OBS:Qt:obs64.exe', itemEnabled: true },
        {
          itemName: 'Minecraft 1.21',
          itemValue: 'Minecraft 1.21:GLFW30:javaw.exe',
          itemEnabled: true,
        },
      ]),
    ).toBe('Minecraft 1.21:GLFW30:javaw.exe')

    expect(() =>
      selectMinecraftWindow([
        { itemName: 'Minecraft A', itemValue: 'A:GLFW30:javaw.exe', itemEnabled: true },
        { itemName: 'Minecraft B', itemValue: 'B:GLFW30:javaw.exe', itemEnabled: true },
      ]),
    ).toThrow(/exactly one/)
  })
})

describe('MinecraftObsCompositeAdapter', () => {
  it('rejects black or static gameplay apertures', () => {
    const black = new PNG({ width: 1920, height: 1080 })
    const lit = new PNG({ width: 1920, height: 1080 })
    lit.data.fill(180)

    expect(() => analyzeMinecraftFrames(black, black)).toThrow(/black/)
    expect(() => analyzeMinecraftFrames(lit, lit)).toThrow(/static/)
  })

  it('builds game, audio, and overlay layers then restores all OBS state', async () => {
    const { client, calls } = harness()
    const adapter = new MinecraftObsCompositeAdapter(client, options)

    await adapter.prepare()
    await adapter.updateSource('http://127.0.0.1:3012/minecraft-gameplay.html?overlay=1')
    const screenshot = await adapter.capture()
    await adapter.dispose()
    await adapter.dispose()

    expect(PNG.sync.read(screenshot)).toEqual(
      expect.objectContaining({ width: 1920, height: 1080 }),
    )
    expect(calls).toContainEqual([
      'SetVideoSettings',
      expect.objectContaining({
        baseWidth: 1920,
        baseHeight: 1080,
        outputWidth: 1920,
        outputHeight: 1080,
      }),
    ])
    expect(calls).toContainEqual([
      'SetSceneItemTransform',
      {
        sceneName: options.sceneName,
        sceneItemId: 11,
        sceneItemTransform: expect.objectContaining({
          positionX: 216,
          positionY: 112,
          boundsWidth: 1488,
          boundsHeight: 837,
        }),
      },
    ])
    expect(calls).toContainEqual([
      'CreateSourceFilter',
      expect.objectContaining({
        sourceName: options.gameAudioSourceName,
        filterName: options.duckingFilterName,
        filterKind: 'compressor_filter',
        filterSettings: expect.objectContaining({
          sidechain_source: options.sourceName,
        }),
      }),
    ])
    expect(calls).toContainEqual([
      'SetInputSettings',
      expect.objectContaining({
        inputName: options.sourceName,
        inputSettings: expect.objectContaining({
          url: 'http://127.0.0.1:3012/minecraft-gameplay.html?overlay=1',
        }),
      }),
    ])
    expect(calls).toContainEqual([
      'SetVideoSettings',
      expect.objectContaining({
        baseWidth: 1080,
        baseHeight: 1920,
        outputWidth: 1080,
        outputHeight: 1920,
      }),
    ])
    expect(calls).toContainEqual(['SetCurrentProgramScene', { sceneName: 'Original' }])
    expect(calls).toContainEqual(['RemoveInput', { inputName: options.sourceName }])
    expect(calls).toContainEqual(['RemoveInput', { inputName: options.gameAudioSourceName }])
    expect(calls).toContainEqual(['RemoveInput', { inputName: options.gameSourceName }])
    expect(client.disconnect).toHaveBeenCalledOnce()
  })

  it('rolls back partial setup failures without leaving temporary resources', async () => {
    const { client, calls } = harness('SetCurrentProgramScene')
    const adapter = new MinecraftObsCompositeAdapter(client, options)

    await expect(adapter.prepare()).rejects.toThrow('injected composite failure')

    expect(calls).toContainEqual(['RemoveInput', { inputName: options.sourceName }])
    expect(calls).toContainEqual(['RemoveInput', { inputName: options.gameAudioSourceName }])
    expect(calls).toContainEqual(['RemoveInput', { inputName: options.gameSourceName }])
    expect(calls).toContainEqual(['RemoveScene', { sceneName: options.sceneName }])
    expect(client.disconnect).toHaveBeenCalledOnce()
  })
})

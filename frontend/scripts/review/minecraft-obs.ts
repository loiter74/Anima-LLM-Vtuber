import { PNG } from 'pngjs'
import type { ObsClient, ObsPreviewOptions, ReviewObsAdapter } from './obs'

interface PropertyItem {
  itemName?: unknown
  itemValue?: unknown
  itemEnabled?: unknown
}

export interface MinecraftObsCompositeOptions extends ObsPreviewOptions {
  gameSourceName: string
  gameAudioSourceName: string
  duckingFilterName: string
  frameDelayMs?: number
}

interface InputSnapshot {
  settings: Record<string, unknown>
  monitorType?: string
  volumeMul?: number
}

export function analyzeMinecraftFrames(first: PNG, second: PNG): void {
  if (first.width !== second.width || first.height !== second.height) {
    throw new Error('OBS Minecraft frame dimensions changed between captures')
  }
  const left = Math.round((216 / 1920) * first.width)
  const top = Math.round((112 / 1080) * first.height)
  const right = Math.round((1704 / 1920) * first.width)
  const bottom = Math.round((949 / 1080) * first.height)
  let sampled = 0
  let litPixels = 0
  let changedPixels = 0
  for (let y = top; y < bottom; y += 2) {
    for (let x = left; x < right; x += 2) {
      const offset = (y * first.width + x) * 4
      const firstLuminance = Math.max(
        first.data[offset],
        first.data[offset + 1],
        first.data[offset + 2],
      )
      const secondLuminance = Math.max(
        second.data[offset],
        second.data[offset + 1],
        second.data[offset + 2],
      )
      sampled += 1
      if (firstLuminance > 16 || secondLuminance > 16) litPixels += 1
      const delta =
        Math.abs(first.data[offset] - second.data[offset]) +
        Math.abs(first.data[offset + 1] - second.data[offset + 1]) +
        Math.abs(first.data[offset + 2] - second.data[offset + 2])
      if (delta >= 24) changedPixels += 1
    }
  }
  if (litPixels / sampled < 0.08) {
    throw new Error('OBS Minecraft gameplay aperture is black')
  }
  if (changedPixels / sampled < 0.0005) {
    throw new Error('OBS Minecraft gameplay aperture is static')
  }
}

export function selectMinecraftWindow(items: readonly PropertyItem[]): string {
  const candidates = items.filter((item) => {
    if (item.itemEnabled === false) return false
    const name = typeof item.itemName === 'string' ? item.itemName : ''
    const value = typeof item.itemValue === 'string' ? item.itemValue : ''
    return `${name} ${value}`.toLowerCase().includes('javaw.exe')
  })
  if (candidates.length !== 1 || typeof candidates[0]?.itemValue !== 'string') {
    throw new Error(
      `Minecraft review requires exactly one enabled javaw.exe window; found ${candidates.length}`,
    )
  }
  return candidates[0].itemValue
}

export class MinecraftObsCompositeAdapter implements ReviewObsAdapter {
  private connected = false
  private prepared = false
  private disposed = false
  private previousScene: string | null = null
  private previousVideoSettings: Record<string, unknown> | null = null
  private createdScene = false
  private readonly createdInputs: string[] = []
  private readonly inputSnapshots = new Map<string, InputSnapshot>()
  private createdDuckingFilter = false

  constructor(
    private readonly client: ObsClient,
    private readonly options: MinecraftObsCompositeOptions,
  ) {}

  async prepare(): Promise<void> {
    await this.client.connect(this.options.url, this.options.password, { rpcVersion: 1 })
    this.connected = true
    try {
      const [stream, record] = await Promise.all([
        this.client.call('GetStreamStatus'),
        this.client.call('GetRecordStatus'),
      ])
      if (stream.outputActive === true || record.outputActive === true) {
        throw new Error('OBS review refuses to run while streaming or recording')
      }

      const current = await this.client.call('GetCurrentProgramScene')
      this.previousScene =
        typeof current.currentProgramSceneName === 'string' ? current.currentProgramSceneName : null
      this.previousVideoSettings = await this.client.call('GetVideoSettings')
      await this.client.call('SetVideoSettings', {
        ...this.previousVideoSettings,
        baseWidth: this.options.width,
        baseHeight: this.options.height,
        outputWidth: this.options.width,
        outputHeight: this.options.height,
      })

      const sceneList = await this.client.call('GetSceneList')
      const scenes = Array.isArray(sceneList.scenes) ? sceneList.scenes : []
      if (
        !scenes.some(
          (scene) =>
            scene &&
            typeof scene === 'object' &&
            (scene as Record<string, unknown>).sceneName === this.options.sceneName,
        )
      ) {
        await this.client.call('CreateScene', { sceneName: this.options.sceneName })
        this.createdScene = true
      }

      const inputList = await this.client.call('GetInputList')
      const inputs = Array.isArray(inputList.inputs) ? inputList.inputs : []
      const existingNames = new Set(
        inputs
          .map((input) =>
            input && typeof input === 'object'
              ? (input as Record<string, unknown>).inputName
              : undefined,
          )
          .filter((name): name is string => typeof name === 'string'),
      )

      const gameItemId = await this.ensureInput(
        this.options.gameSourceName,
        'game_capture',
        { capture_mode: 'window' },
        existingNames,
      )
      const properties = await this.client.call('GetInputPropertiesListPropertyItems', {
        inputName: this.options.gameSourceName,
        propertyName: 'window',
      })
      const window = selectMinecraftWindow(
        Array.isArray(properties.propertyItems) ? properties.propertyItems : [],
      )
      await this.client.call('SetInputSettings', {
        inputName: this.options.gameSourceName,
        inputSettings: {
          capture_mode: 'window',
          window,
          priority: 2,
        },
        overlay: true,
      })
      await this.client.call('SetSceneItemTransform', {
        sceneName: this.options.sceneName,
        sceneItemId: gameItemId,
        sceneItemTransform: {
          positionX: 216,
          positionY: 112,
          boundsType: 'OBS_BOUNDS_STRETCH',
          boundsWidth: 1488,
          boundsHeight: 837,
        },
      })
      await this.client.call('SetSceneItemIndex', {
        sceneName: this.options.sceneName,
        sceneItemId: gameItemId,
        sceneItemIndex: 0,
      })

      await this.ensureInput(
        this.options.gameAudioSourceName,
        'wasapi_process_output_capture',
        { window },
        existingNames,
        true,
      )
      await this.client.call('SetInputSettings', {
        inputName: this.options.gameAudioSourceName,
        inputSettings: { window },
        overlay: true,
      })
      await this.client.call('SetInputVolume', {
        inputName: this.options.gameAudioSourceName,
        inputVolumeMul: 0.35,
      })

      const overlayItemId = await this.ensureInput(
        this.options.sourceName,
        'browser_source',
        {
          url: 'about:blank',
          width: this.options.width,
          height: this.options.height,
          shutdown: true,
          reroute_audio: true,
        },
        existingNames,
        false,
        true,
      )
      await this.client.call('SetInputSettings', {
        inputName: this.options.sourceName,
        inputSettings: {
          width: this.options.width,
          height: this.options.height,
          reroute_audio: true,
        },
        overlay: true,
      })
      await this.client.call('SetInputAudioMonitorType', {
        inputName: this.options.sourceName,
        monitorType: 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT',
      })
      await this.client.call('SetSceneItemTransform', {
        sceneName: this.options.sceneName,
        sceneItemId: overlayItemId,
        sceneItemTransform: {
          positionX: 0,
          positionY: 0,
          boundsType: 'OBS_BOUNDS_STRETCH',
          boundsWidth: this.options.width,
          boundsHeight: this.options.height,
        },
      })
      await this.client.call('SetSceneItemIndex', {
        sceneName: this.options.sceneName,
        sceneItemId: overlayItemId,
        sceneItemIndex: 2,
      })

      const filters = await this.client.call('GetSourceFilterList', {
        sourceName: this.options.gameAudioSourceName,
      })
      const filterList = Array.isArray(filters.filters) ? filters.filters : []
      if (
        !filterList.some(
          (filter) =>
            filter &&
            typeof filter === 'object' &&
            (filter as Record<string, unknown>).filterName === this.options.duckingFilterName,
        )
      ) {
        await this.client.call('CreateSourceFilter', {
          sourceName: this.options.gameAudioSourceName,
          filterName: this.options.duckingFilterName,
          filterKind: 'compressor_filter',
          filterSettings: {
            ratio: 10,
            threshold: -30,
            attack_time: 50,
            release_time: 300,
            output_gain: 0,
            sidechain_source: this.options.sourceName,
          },
        })
        this.createdDuckingFilter = true
      }

      await this.client.call('SetCurrentProgramScene', { sceneName: this.options.sceneName })
      this.prepared = true
    } catch (error) {
      await this.rollback()
      throw error
    }
  }

  async updateSource(reviewUrl: string): Promise<void> {
    if (!this.prepared) throw new Error('Minecraft OBS composite is not prepared')
    await this.client.call('SetInputSettings', {
      inputName: this.options.sourceName,
      inputSettings: {
        url: reviewUrl,
        width: this.options.width,
        height: this.options.height,
        reroute_audio: true,
      },
      overlay: true,
    })
    await this.client.call('PressInputPropertiesButton', {
      inputName: this.options.sourceName,
      propertyName: 'refreshnocache',
    })
  }

  async capture(): Promise<Buffer> {
    if (!this.prepared) throw new Error('Minecraft OBS composite is not prepared')
    const first = await this.captureFrame()
    await new Promise<void>((resolve) =>
      globalThis.setTimeout(resolve, this.options.frameDelayMs ?? 300),
    )
    const second = await this.captureFrame()
    analyzeMinecraftFrames(first.png, second.png)
    return second.screenshot
  }

  private async captureFrame(): Promise<{ screenshot: Buffer; png: PNG }> {
    const response = await this.client.call('GetSourceScreenshot', {
      sourceName: this.options.sceneName,
      imageFormat: 'png',
      imageWidth: this.options.width,
      imageHeight: this.options.height,
      imageCompressionQuality: -1,
    })
    if (typeof response.imageData !== 'string') {
      throw new Error('OBS did not return a Minecraft scene screenshot')
    }
    const match = /^data:image\/png;base64,(.+)$/.exec(response.imageData)
    if (!match) throw new Error('OBS Minecraft screenshot is not a PNG data URL')
    const screenshot = Buffer.from(match[1], 'base64')
    const png = PNG.sync.read(screenshot)
    if (png.width !== this.options.width || png.height !== this.options.height) {
      throw new Error(
        `OBS screenshot dimensions ${png.width}x${png.height} do not match ${this.options.width}x${this.options.height}`,
      )
    }
    return { screenshot, png }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    await this.rollback()
  }

  private async ensureInput(
    inputName: string,
    inputKind: string,
    inputSettings: Record<string, unknown>,
    existingNames: ReadonlySet<string>,
    captureVolume = false,
    captureMonitor = false,
  ): Promise<number> {
    if (existingNames.has(inputName)) {
      const settings = await this.client.call('GetInputSettings', { inputName })
      const snapshot: InputSnapshot = {
        settings:
          settings.inputSettings &&
          typeof settings.inputSettings === 'object' &&
          !Array.isArray(settings.inputSettings)
            ? { ...(settings.inputSettings as Record<string, unknown>) }
            : {},
      }
      if (captureVolume) {
        const volume = await this.client.call('GetInputVolume', { inputName })
        if (typeof volume.inputVolumeMul === 'number') snapshot.volumeMul = volume.inputVolumeMul
      }
      if (captureMonitor) {
        const monitor = await this.client.call('GetInputAudioMonitorType', { inputName })
        if (typeof monitor.monitorType === 'string') snapshot.monitorType = monitor.monitorType
      }
      this.inputSnapshots.set(inputName, snapshot)
      const item = await this.client.call('GetSceneItemId', {
        sceneName: this.options.sceneName,
        sourceName: inputName,
      })
      if (typeof item.sceneItemId !== 'number') {
        throw new Error(`OBS did not return a scene item for ${inputName}`)
      }
      return item.sceneItemId
    }

    const created = await this.client.call('CreateInput', {
      sceneName: this.options.sceneName,
      inputName,
      inputKind,
      inputSettings,
      sceneItemEnabled: true,
    })
    this.createdInputs.push(inputName)
    if (typeof created.sceneItemId !== 'number') {
      throw new Error(`OBS did not return a new scene item for ${inputName}`)
    }
    return created.sceneItemId
  }

  private async rollback(): Promise<void> {
    if (!this.connected) return
    try {
      if (this.previousScene) {
        await this.client
          .call('SetCurrentProgramScene', { sceneName: this.previousScene })
          .catch(() => {})
      }
      if (this.createdDuckingFilter) {
        await this.client
          .call('RemoveSourceFilter', {
            sourceName: this.options.gameAudioSourceName,
            filterName: this.options.duckingFilterName,
          })
          .catch(() => {})
        this.createdDuckingFilter = false
      }
      for (const [inputName, snapshot] of this.inputSnapshots) {
        await this.client
          .call('SetInputSettings', {
            inputName,
            inputSettings: snapshot.settings,
            overlay: false,
          })
          .catch(() => {})
        if (snapshot.volumeMul !== undefined) {
          await this.client
            .call('SetInputVolume', { inputName, inputVolumeMul: snapshot.volumeMul })
            .catch(() => {})
        }
        if (snapshot.monitorType) {
          await this.client
            .call('SetInputAudioMonitorType', {
              inputName,
              monitorType: snapshot.monitorType,
            })
            .catch(() => {})
        }
      }
      for (const inputName of [...this.createdInputs].reverse()) {
        await this.client.call('RemoveInput', { inputName }).catch(() => {})
      }
      this.createdInputs.length = 0
      if (this.createdScene) {
        await this.client.call('RemoveScene', { sceneName: this.options.sceneName }).catch(() => {})
        this.createdScene = false
      }
      if (this.previousVideoSettings) {
        await this.client.call('SetVideoSettings', this.previousVideoSettings).catch(() => {})
      }
    } finally {
      this.prepared = false
      this.connected = false
      await this.client.disconnect().catch(() => {})
    }
  }
}

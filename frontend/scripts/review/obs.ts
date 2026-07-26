export interface ObsClient {
  connect(url: string, password?: string, options?: { rpcVersion?: number }): Promise<unknown>
  call(requestType: string, requestData?: Record<string, unknown>): Promise<Record<string, unknown>>
  disconnect(): Promise<void>
}

export interface ObsPreviewOptions {
  url: string
  password?: string
  sceneName: string
  sourceName: string
  width: number
  height: number
  enableAudioMonitoring?: boolean
}

export class ObsPreviewAdapter {
  private connected = false
  private prepared = false
  private previousScene: string | null = null
  private previousInputSettings: Record<string, unknown> | null = null
  private previousMonitorType: string | null = null
  private audioSettingsChanged = false
  private createdScene = false
  private createdInput = false

  constructor(
    private readonly client: ObsClient,
    private readonly options: ObsPreviewOptions,
  ) {}

  async prepare(): Promise<void> {
    await this.client.connect(this.options.url, this.options.password, { rpcVersion: 1 })
    this.connected = true
    try {
      const stream = await this.client.call('GetStreamStatus')
      const record = await this.client.call('GetRecordStatus')
      if (stream.outputActive === true || record.outputActive === true) {
        throw new Error('OBS review refuses to run while streaming or recording')
      }

      const current = await this.client.call('GetCurrentProgramScene')
      this.previousScene =
        typeof current.currentProgramSceneName === 'string' ? current.currentProgramSceneName : null
      const sceneList = await this.client.call('GetSceneList')
      const scenes = Array.isArray(sceneList.scenes) ? sceneList.scenes : []
      const sceneExists = scenes.some(
        (scene) =>
          scene &&
          typeof scene === 'object' &&
          (scene as Record<string, unknown>).sceneName === this.options.sceneName,
      )
      if (!sceneExists) {
        await this.client.call('CreateScene', { sceneName: this.options.sceneName })
        this.createdScene = true
      }

      const inputList = await this.client.call('GetInputList', { inputKind: 'browser_source' })
      const inputs = Array.isArray(inputList.inputs) ? inputList.inputs : []
      const inputExists = inputs.some(
        (input) =>
          input &&
          typeof input === 'object' &&
          (input as Record<string, unknown>).inputName === this.options.sourceName,
      )
      if (inputExists && this.options.enableAudioMonitoring) {
        const settings = await this.client.call('GetInputSettings', {
          inputName: this.options.sourceName,
        })
        this.previousInputSettings =
          settings.inputSettings &&
          typeof settings.inputSettings === 'object' &&
          !Array.isArray(settings.inputSettings)
            ? { ...(settings.inputSettings as Record<string, unknown>) }
            : {}
        const monitor = await this.client.call('GetInputAudioMonitorType', {
          inputName: this.options.sourceName,
        })
        this.previousMonitorType =
          typeof monitor.monitorType === 'string' ? monitor.monitorType : 'OBS_MONITORING_TYPE_NONE'
      }
      if (!inputExists) {
        await this.client.call('CreateInput', {
          sceneName: this.options.sceneName,
          inputName: this.options.sourceName,
          inputKind: 'browser_source',
          inputSettings: {
            url: 'about:blank',
            width: this.options.width,
            height: this.options.height,
            shutdown: true,
          },
          sceneItemEnabled: true,
        })
        this.createdInput = true
        if (this.options.enableAudioMonitoring) {
          this.previousMonitorType = 'OBS_MONITORING_TYPE_NONE'
        }
      }
      if (this.options.enableAudioMonitoring) {
        await this.client.call('SetInputSettings', {
          inputName: this.options.sourceName,
          inputSettings: { reroute_audio: true },
          overlay: true,
        })
        this.audioSettingsChanged = true
        await this.client.call('SetInputAudioMonitorType', {
          inputName: this.options.sourceName,
          monitorType: 'OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT',
        })
      }
      await this.client.call('SetCurrentProgramScene', { sceneName: this.options.sceneName })
      this.prepared = true
    } catch (error) {
      await this.restoreAudioSettings()
      await this.restorePreviousScene()
      await this.removeCreatedResources()
      await this.client.disconnect().catch(() => {})
      this.connected = false
      throw error
    }
  }

  async updateSource(_reviewUrl: string): Promise<void> {
    if (!this.prepared) throw new Error('OBS preview adapter is not prepared')
    await this.client.call('SetInputSettings', {
      inputName: this.options.sourceName,
      inputSettings: {
        url: _reviewUrl,
        width: this.options.width,
        height: this.options.height,
      },
      overlay: true,
    })
    await this.client.call('PressInputPropertiesButton', {
      inputName: this.options.sourceName,
      propertyName: 'refreshnocache',
    })
  }

  async capture(): Promise<Buffer> {
    if (!this.prepared) throw new Error('OBS preview adapter is not prepared')
    const response = await this.client.call('GetSourceScreenshot', {
      sourceName: this.options.sourceName,
      imageFormat: 'png',
      imageWidth: this.options.width,
      imageHeight: this.options.height,
      imageCompressionQuality: -1,
    })
    if (typeof response.imageData !== 'string') {
      throw new Error('OBS did not return a source screenshot')
    }
    const match = /^data:image\/png;base64,(.+)$/.exec(response.imageData)
    if (!match) throw new Error('OBS source screenshot is not a PNG data URL')
    const screenshot = Buffer.from(match[1], 'base64')
    const png = await import('pngjs').then(({ PNG }) => PNG.sync.read(screenshot))
    if (png.width !== this.options.width || png.height !== this.options.height) {
      throw new Error(
        `OBS screenshot dimensions ${png.width}x${png.height} do not match ${this.options.width}x${this.options.height}`,
      )
    }
    return screenshot
  }

  async dispose(): Promise<void> {
    if (!this.connected) return
    try {
      await this.restoreAudioSettings()
      await this.restorePreviousScene()
    } finally {
      await this.removeCreatedResources()
      this.prepared = false
      this.connected = false
      this.previousInputSettings = null
      this.previousMonitorType = null
      this.previousScene = null
      await this.client.disconnect()
    }
  }

  private async restorePreviousScene(): Promise<void> {
    if (!this.previousScene) return
    await this.client
      .call('SetCurrentProgramScene', { sceneName: this.previousScene })
      .catch(() => {})
  }

  private async removeCreatedResources(): Promise<void> {
    if (this.createdInput) {
      await this.client.call('RemoveInput', { inputName: this.options.sourceName }).catch(() => {})
      this.createdInput = false
    }
    if (this.createdScene) {
      await this.client.call('RemoveScene', { sceneName: this.options.sceneName }).catch(() => {})
      this.createdScene = false
    }
  }

  private async restoreAudioSettings(): Promise<void> {
    if (!this.audioSettingsChanged) return
    if (this.previousInputSettings) {
      await this.client
        .call('SetInputSettings', {
          inputName: this.options.sourceName,
          inputSettings: this.previousInputSettings,
          overlay: false,
        })
        .catch(() => {})
    } else {
      await this.client
        .call('SetInputSettings', {
          inputName: this.options.sourceName,
          inputSettings: { reroute_audio: false },
          overlay: true,
        })
        .catch(() => {})
    }
    await this.client
      .call('SetInputAudioMonitorType', {
        inputName: this.options.sourceName,
        monitorType: this.previousMonitorType ?? 'OBS_MONITORING_TYPE_NONE',
      })
      .catch(() => {})
    this.audioSettingsChanged = false
  }
}

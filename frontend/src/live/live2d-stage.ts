import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import type { Cubism4InternalModel } from 'pixi-live2d-display/cubism4'
import { Events } from '@/constants/socket-events'
import { DisposerStack } from '@/review/disposable'
import type { Live2DAction } from '@/types/live2d'
import type { LiveSocket } from './controller'
import { computeLive2DLayout } from './layout'
import { bindReviewMouthAfterMotion, createReviewVolumeTimelineLipSync } from './review-lip-sync'
import type { Live2DPerformancePlanV1 } from '@/types/socket-events'
import {
  DEFAULT_LIVE2D_PERFORMANCE_PLAN,
  createLive2DPerformanceController,
  Live2DPerformanceController,
} from '@/components/live2d/live2dPerformanceController'
import {
  createCubismParameterAdapter,
  type CubismParameterModel,
} from '@/components/live2d/live2dPerformanceProfile'

const IDLE_VITALITY_PARAMETERS = [
  { name: 'ParamAngleX', factor: 2.3 },
  { name: 'ParamAngleY', factor: 2.3 },
  { name: 'ParamAngleZ', factor: 2.3 },
  { name: 'ParamBodyAngleX', factor: 2.6 },
  { name: 'ParamBodyAngleY', factor: 2.6 },
  { name: 'ParamBodyAngleZ', factor: 2.6 },
  { name: 'ParamBreath', factor: 2.4 },
] as const

const PARAMETER_LIMIT_KNEE_RATIO = 0.8

function softlyLimitParameter(
  value: number,
  defaultValue: number,
  minimum: number,
  maximum: number,
): number {
  const offset = value - defaultValue
  const limit = offset < 0 ? defaultValue - minimum : maximum - defaultValue
  if (!Number.isFinite(limit)) return value
  if (limit <= 0) return defaultValue

  const magnitude = Math.abs(offset)
  const knee = limit * PARAMETER_LIMIT_KNEE_RATIO
  if (magnitude <= knee) return value

  const remaining = limit - knee
  const softened = knee + remaining * (1 - Math.exp(-(magnitude - knee) / remaining))
  return defaultValue + Math.sign(offset) * softened
}

function amplifyIdleMotion(internalModel: Cubism4InternalModel): void {
  if (internalModel.motionManager.state.currentGroup !== 'Idle') return

  for (const { name, factor } of IDLE_VITALITY_PARAMETERS) {
    const index = internalModel.coreModel.getParameterIndex(name)
    if (index < 0) continue
    const current = internalModel.coreModel.getParameterValueByIndex(index)
    const defaultValue = internalModel.coreModel.getParameterDefaultValue?.(index) ?? 0
    const minimum =
      internalModel.coreModel.getParameterMinimumValue?.(index) ?? Number.NEGATIVE_INFINITY
    const maximum =
      internalModel.coreModel.getParameterMaximumValue?.(index) ?? Number.POSITIVE_INFINITY
    internalModel.coreModel.setParameterValueByIndex(
      index,
      softlyLimitParameter(
        defaultValue + (current - defaultValue) * factor,
        defaultValue,
        minimum,
        maximum,
      ),
    )
  }
}

async function configureIdleLoopMotions(internalModel: Cubism4InternalModel): Promise<void> {
  const { motionManager } = internalModel
  const idleGroup = motionManager.groups.idle
  const idleDefinitions = motionManager.definitions[idleGroup] ?? []
  await Promise.all(
    idleDefinitions.map(async (_definition, index) => {
      const motion = await motionManager.loadMotion(idleGroup, index)
      if (!motion) return
      motion.setIsLoop(true)
      motion.setIsLoopFadeIn(false)
    }),
  )
}

export interface Live2DStage {
  ready: Promise<void>
  setMouth(value: number, taskId?: string): void
  playReviewAudio(
    notification: HTMLElement,
    volumes: readonly number[],
    performance?: Live2DPerformancePlanV1,
  ): void
  cancelReviewAudio(): void
  dispose(): void
}

export interface Live2DStageOptions {
  readonly resizeTo?: Window | HTMLElement
  readonly idleVitality?: boolean
}

export function createLive2DStage(
  socket: LiveSocket,
  options: Live2DStageOptions = {},
): Live2DStage {
  const canvas = document.getElementById('live2dCanvas')
  const state = document.getElementById('modelStatus')
  const audioStatus = document.getElementById('audioStatus')
  if (!(canvas instanceof HTMLCanvasElement) || !state) {
    return {
      ready: Promise.resolve(),
      setMouth() {},
      playReviewAudio() {},
      cancelReviewAudio() {},
      dispose() {},
    }
  }

  const disposers = new DisposerStack()
  let disposed = false
  let app: PIXI.Application | null = null
  let setStageMouth: (value: number) => void = () => {}
  let setReviewMouthSampler: (callback: (() => void) | null) => void = () => {}
  let markReviewMouthApplied = (): void => {}
  let activeMouthTaskId = ''
  let reviewLipSync: ReturnType<typeof createReviewVolumeTimelineLipSync> | null = null
  let performanceController: Live2DPerformanceController | null = null

  const ready = (async (): Promise<void> => {
    try {
      app = new PIXI.Application({
        view: canvas,
        resizeTo: options.resizeTo ?? window,
        backgroundAlpha: 0,
        autoStart: true,
      })
      disposers.add(() => {
        app?.stop()
        app?.destroy(false, { children: true, texture: false, baseTexture: false })
        app = null
      })

      const model = await Live2DModel.from('/live2d/mao/Mao.model3.json', {
        autoInteract: false,
      })
      if (disposed || !app) {
        model.destroy()
        return
      }
      await configureIdleLoopMotions(model.internalModel as Cubism4InternalModel)
      const baseWidth = model.width / model.scale.x
      const baseHeight = model.height / model.scale.y
      const mouthBinding = bindReviewMouthAfterMotion(
        model.internalModel as Parameters<typeof bindReviewMouthAfterMotion>[0],
        (value) => {
          markReviewMouthApplied()
          if (!audioStatus || value <= 0.02) return
          audioStatus.dataset.lipSyncState = 'observed'
          audioStatus.dataset.lipSyncAppliedCount = String(
            Number(audioStatus.dataset.lipSyncAppliedCount ?? 0) + 1,
          )
          audioStatus.dataset.lipSyncPeak = String(
            Math.max(Number(audioStatus.dataset.lipSyncPeak ?? 0), value),
          )
          audioStatus.dataset.lastLipSyncTaskId = activeMouthTaskId
          audioStatus.dataset.lastLipSyncAppliedAt = String(Date.now())
        },
      )
      setStageMouth = mouthBinding.setMouth
      setReviewMouthSampler = mouthBinding.setBeforeApply
      disposers.add(() => mouthBinding.dispose())
      const coreModel = model.internalModel.coreModel as CubismParameterModel
      performanceController = createLive2DPerformanceController(
        createCubismParameterAdapter(coreModel),
      )
      setReviewMouthSampler(() => {
        performanceController?.tick()
        if (options.idleVitality) {
          amplifyIdleMotion(model.internalModel as Cubism4InternalModel)
        }
        reviewLipSync?.sample()
      })
      disposers.add(() => performanceController?.destroy())

      const layout = (): void => {
        if (!app) return
        const { scale, x, y } = computeLive2DLayout({
          screenWidth: app.screen.width,
          screenHeight: app.screen.height,
          baseWidth,
          baseHeight,
        })
        model.scale.set(scale)
        model.anchor.set(0.5, 0.5)
        model.position.set(x, y)
      }
      const onLive2DAction = (value: unknown): void => {
        const action = value as Live2DAction
        if (action.type === 'expression' && action.name) model.expression(action.name)
        if (action.type === 'motion' && action.group) model.motion(action.group, action.index ?? 0)
      }

      app.stage.addChild(model)
      layout()
      window.addEventListener('resize', layout)
      disposers.add(() => window.removeEventListener('resize', layout))
      socket.on(Events.CHAT.LIVE2D_ACTION, onLive2DAction)
      disposers.add(() => socket.off(Events.CHAT.LIVE2D_ACTION, onLive2DAction))
      state.textContent = 'Live2D 已加载'
      state.dataset.state = 'live'
    } catch (error) {
      if (disposed) return
      state.textContent = 'Live2D 加载失败'
      state.dataset.state = 'error'
      console.error('[Live] Live2D initialization failed', error)
    }
  })()

  return {
    ready,
    setMouth(value: number, taskId = ''): void {
      if (taskId) activeMouthTaskId = taskId
      setStageMouth(value)
    },
    playReviewAudio(
      notification: HTMLElement,
      volumes: readonly number[],
      performance = DEFAULT_LIVE2D_PERFORMANCE_PLAN,
    ): void {
      const audio = notification.querySelector<HTMLAudioElement>('#reviewAudio')
      if (!audio) throw new Error('TTS review audio is unavailable')
      const taskId = `${performance.base}:${performance.accent}:${audio.currentSrc || audio.src}`
      performanceController?.arm(performance, taskId)
      notification.dataset.performanceBase = performance.base
      notification.dataset.performanceAccent = performance.accent
      markReviewMouthApplied = () => {
        notification.dataset.lipSync = 'observed'
      }
      reviewLipSync?.stop()
      reviewLipSync = createReviewVolumeTimelineLipSync({
        audio,
        volumes,
        setMouth: setStageMouth,
        manualSampling: true,
      })
      const stop = (): void => {
        reviewLipSync?.stop()
        performanceController?.finish(taskId)
      }
      audio.addEventListener('ended', stop, { once: true })
      audio.addEventListener('error', stop, { once: true })
      reviewLipSync.start()
      void audio
        .play()
        .then(() => performanceController?.start(taskId))
        .catch(() => {
          audio.dataset.complete = 'blocked'
          performanceController?.cancel()
          stop()
        })
    },
    cancelReviewAudio(): void {
      reviewLipSync?.stop()
      reviewLipSync = null
      setStageMouth(0)
      performanceController?.cancel()
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      reviewLipSync?.stop()
      performanceController?.cancel()
      disposers.dispose()
    },
  }
}

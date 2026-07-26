import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import { Events } from '@/constants/socket-events'
import { DisposerStack } from '@/review/disposable'
import type { Live2DAction } from '@/types/live2d'
import type { LiveSocket } from './controller'
import { computeLive2DLayout } from './layout'
import { bindReviewMouthAfterMotion, createReviewVolumeTimelineLipSync } from './review-lip-sync'

export interface Live2DStage {
  ready: Promise<void>
  playReviewAudio(notification: HTMLElement, volumes: readonly number[]): void
  dispose(): void
}

export function createLive2DStage(socket: LiveSocket): Live2DStage {
  const canvas = document.getElementById('live2dCanvas')
  const state = document.getElementById('modelStatus')
  if (!(canvas instanceof HTMLCanvasElement) || !state) {
    return { ready: Promise.resolve(), playReviewAudio() {}, dispose() {} }
  }

  const disposers = new DisposerStack()
  let disposed = false
  let app: PIXI.Application | null = null
  let setReviewMouth: (value: number) => void = () => {}
  let setReviewMouthSampler: (callback: (() => void) | null) => void = () => {}
  let stopReviewMotion = (): void => {}
  let restartIdleMotion = (): void => {}
  let markReviewMouthApplied = (): void => {}
  let reviewLipSync: ReturnType<typeof createReviewVolumeTimelineLipSync> | null = null

  const ready = (async (): Promise<void> => {
    try {
      app = new PIXI.Application({
        view: canvas,
        resizeTo: window,
        backgroundAlpha: 0,
        autoStart: true,
      })
      disposers.add(() => {
        app?.stop()
        app?.destroy(false, { children: true, texture: false, baseTexture: false })
        app = null
      })

      const model = await Live2DModel.from('/live2d/hiyori/Hiyori.model3.json', {
        autoInteract: false,
      })
      if (disposed || !app) {
        model.destroy()
        return
      }
      const baseWidth = model.width / model.scale.x
      const baseHeight = model.height / model.scale.y
      const mouthBinding = bindReviewMouthAfterMotion(
        model.internalModel as Parameters<typeof bindReviewMouthAfterMotion>[0],
        () => markReviewMouthApplied(),
      )
      setReviewMouth = mouthBinding.setMouth
      setReviewMouthSampler = mouthBinding.setBeforeApply
      disposers.add(() => mouthBinding.dispose())
      stopReviewMotion = (): void => {
        try {
          model.internalModel.motionManager?.stopAllMotions()
        } catch {}
      }
      restartIdleMotion = (): void => {
        try {
          void model.motion('Idle', 0)
        } catch {}
      }

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
    playReviewAudio(notification: HTMLElement, volumes: readonly number[]): void {
      const audio = notification.querySelector<HTMLAudioElement>('#reviewAudio')
      if (!audio) throw new Error('TTS review audio is unavailable')
      stopReviewMotion()
      markReviewMouthApplied = () => {
        notification.dataset.lipSync = 'observed'
      }
      setReviewMouthSampler(null)
      reviewLipSync?.stop()
      reviewLipSync = createReviewVolumeTimelineLipSync({
        audio,
        volumes,
        setMouth: setReviewMouth,
        manualSampling: true,
      })
      setReviewMouthSampler(reviewLipSync.sample)
      const stop = (): void => {
        setReviewMouthSampler(null)
        reviewLipSync?.stop()
        restartIdleMotion()
      }
      audio.addEventListener('ended', stop, { once: true })
      audio.addEventListener('error', stop, { once: true })
      reviewLipSync.start()
      void audio.play().catch(() => {
        audio.dataset.complete = 'blocked'
        stop()
      })
    },
    dispose(): void {
      if (disposed) return
      disposed = true
      reviewLipSync?.stop()
      disposers.dispose()
    },
  }
}

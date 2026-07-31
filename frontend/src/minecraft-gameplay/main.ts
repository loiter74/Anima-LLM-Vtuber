import * as PIXI from 'pixi.js'

import type { LiveSocket } from '@/live/controller'
import { createLive2DStage } from '@/live/live2d-stage'
import { mountMinecraftGameplayShell } from './page'
import 'virtual:uno.css'
import './styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI

const socket: LiveSocket = {
  on() {
    return socket
  },
  off() {
    return socket
  },
}

const shell = mountMinecraftGameplayShell(document, new URLSearchParams(window.location.search))
const avatar = shell.element.querySelector<HTMLElement>('.game-avatar')
const stage = createLive2DStage(socket, { resizeTo: avatar ?? window })
const reviewRuntime = shell.element.querySelector<HTMLElement>('.minecraft-review-runtime')
const reviewAudio = reviewRuntime?.querySelector<HTMLAudioElement>('#reviewAudio')

if (reviewRuntime && reviewAudio) {
  const volumes = JSON.parse(reviewRuntime.dataset.mouthTimeline ?? '[]') as number[]
  reviewAudio.addEventListener(
    'ended',
    () => {
      reviewAudio.dataset.complete = 'true'
    },
    { once: true },
  )
  reviewAudio.addEventListener(
    'error',
    () => {
      reviewAudio.dataset.complete = 'error'
    },
    { once: true },
  )
  void stage.ready.then(() => stage.playReviewAudio(reviewRuntime, volumes))
}

const resize = (): void => {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
  shell.element.style.setProperty('--broadcast-scale', String(scale))
}

let disposed = false
const dispose = (): void => {
  if (disposed) return
  disposed = true
  window.removeEventListener('resize', resize)
  stage.dispose()
  shell.dispose()
}

resize()
window.addEventListener('resize', resize)
window.addEventListener('beforeunload', dispose, { once: true })

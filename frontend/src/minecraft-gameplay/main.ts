import * as PIXI from 'pixi.js'
import { io } from 'socket.io-client'

import type { LiveSocket } from '@/live/controller'
import { Events } from '@/constants/socket-events'
import { isStageIOView, type StageIOView } from '@/types/minecraft-stage'
import { createLive2DStage } from '@/review/live2d-stage'
import { mountMinecraftGameplayShell } from './page'
import 'virtual:uno.css'
import './styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI

const socketClient = io(window.location.origin, {
  path: '/socket.io/',
  transports: ['websocket', 'polling'],
  reconnection: true,
  withCredentials: true,
})
const socket = socketClient as unknown as LiveSocket

const shell = mountMinecraftGameplayShell(document, new URLSearchParams(window.location.search))
const search = new URLSearchParams(window.location.search)
const projectedStages = new Map<string, StageIOView>()
const onStageProjection = (value: unknown): void => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return
  const envelope = value as Record<string, unknown>
  const payload = envelope.payload
  if (envelope.projection_kind !== 'stage' || !isStageIOView(payload)) return
  const requestedRun = search.get('runId')
  const requestedMission = search.get('missionId')
  if (requestedRun && payload.run_id !== requestedRun) return
  if (requestedMission && payload.mission_id !== requestedMission) return
  projectedStages.set(payload.stage_id, payload)
  shell.updateWalkthrough(
    [...projectedStages.values()].sort(
      (left, right) => left.ordinal - right.ordinal || left.stage_id.localeCompare(right.stage_id),
    ),
  )
}
socketClient.on(Events.MINECRAFT.STAGE_PROJECTION, onStageProjection)
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
  socketClient.off(Events.MINECRAFT.STAGE_PROJECTION, onStageProjection)
  socketClient.disconnect()
  stage.dispose()
  shell.dispose()
}

resize()
window.addEventListener('resize', resize)
window.addEventListener('beforeunload', dispose, { once: true })

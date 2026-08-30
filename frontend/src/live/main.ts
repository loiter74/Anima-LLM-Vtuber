import { io } from 'socket.io-client'
import * as PIXI from 'pixi.js'
import { mountTtsFailoverReviewNotification } from '@/tts-failover/main'
import { DisposerStack } from '@/review/disposable'
import { bootstrapLiveSession } from './bootstrap'
import { createLiveAudioController } from './audio'
import { createLiveBgmController } from './bgm'
import type { LiveSocket } from './controller'
import { applyLiveReviewLayout } from '@/review/layout'
import { createLive2DStage } from '@/review/live2d-stage'
import { parseReviewMouthTimeline } from '@/review/review-lip-sync'
import { mountLive2DPerformanceReview } from '@/review/live2d-performance/main'
import { PUBLIC_LIVE_SOCKET_AUTH, startPublicLiveSocket } from '@/shared/transport/publicLiveSocket'
import { createPublicMediaOwnership } from '@/shared/broadcast/mediaOwnership'
import type { LiveSocketRuntime } from './socket-runtime'
import { createDomLiveView } from './view'
import 'virtual:uno.css'
import './styles.css'
import '@/shared/broadcast/public-activity.css'
import '@/tts-failover/styles.css'
import '@/review/live2d-performance/styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI
applyLiveReviewLayout(document.documentElement)
const search = new URLSearchParams(window.location.search)
const mediaOwnership = createPublicMediaOwnership(search, 'active')
const liveView = createDomLiveView(document)
let live2dStage: ReturnType<typeof createLive2DStage> | null = null

function createNetworkRuntime(): LiveSocketRuntime {
  const socket = io(window.location.origin, {
    path: '/socket.io/',
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 3000,
    reconnectionAttempts: Infinity,
    timeout: 120000,
    autoConnect: false,
    withCredentials: true,
    auth: PUBLIC_LIVE_SOCKET_AUTH,
  })
  const liveSocket: LiveSocket = {
    on(event, handler) {
      socket.on(event, handler)
      return liveSocket
    },
    off(event, handler) {
      socket.off(event, handler)
      return liveSocket
    },
  }
  return {
    mode: 'network',
    socket: liveSocket,
    start() {
      startPublicLiveSocket(socket, liveView)
    },
    dispose() {
      socket.disconnect()
    },
  }
}

const session = bootstrapLiveSession({
  search,
  view: liveView,
  createNetworkRuntime,
  onPublicVisualCue: (cue) => live2dStage?.applyPublicCue(cue),
})

const pageDisposers = new DisposerStack()
let pageDisposed = false
const stage = createLive2DStage(session.socket, { idleVitality: true })
live2dStage = stage
const liveBgm = createLiveBgmController(document, search, { ownership: mediaOwnership })
const liveAudio = createLiveAudioController(session.socket, document, stage.setMouth, liveBgm, {
  ownership: mediaOwnership,
})
pageDisposers.add(() => mediaOwnership.dispose())
pageDisposers.add(() => session.dispose())
pageDisposers.add(() => liveAudio.dispose())
pageDisposers.add(() => liveBgm.dispose())
pageDisposers.add(() => stage.dispose())
const disposePage = (): void => {
  if (pageDisposed) return
  pageDisposed = true
  pageDisposers.dispose()
}
window.addEventListener('beforeunload', disposePage, { once: true })
pageDisposers.add(() => window.removeEventListener('beforeunload', disposePage))

void stage.ready.finally(() => {
  if (pageDisposed) return
  const notification = mountTtsFailoverReviewNotification(document, search, { autoplay: false })
  if (notification) {
    pageDisposers.add(() => notification.dispose())
    const volumes = parseReviewMouthTimeline(search.get('mouthTimeline'))
    stage.playReviewAudio(notification.element, volumes)
  }
  const performanceReview = mountLive2DPerformanceReview(document, search, stage)
  if (performanceReview) pageDisposers.add(() => performanceReview.dispose())
  session.start()
})

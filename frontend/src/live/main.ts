import { io } from 'socket.io-client'
import * as PIXI from 'pixi.js'
import { mountTtsFailoverReviewNotification } from '@/tts-failover/main'
import { DisposerStack } from '@/review/disposable'
import { bootstrapLiveSession } from './bootstrap'
import { createLiveAudioController } from './audio'
import type { LiveSocket } from './controller'
import { applyLiveReviewLayout } from './layout'
import { createLive2DStage } from './live2d-stage'
import { parseReviewMouthTimeline } from './review-lip-sync'
import { mountLive2DPerformanceReview } from '@/live2d-performance/main'
import type { LiveSocketRuntime } from './socket-runtime'
import { createDomLiveView } from './view'
import 'virtual:uno.css'
import './styles.css'
import '@/tts-failover/styles.css'
import '@/live2d-performance/styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI
applyLiveReviewLayout(document.documentElement)
const search = new URLSearchParams(window.location.search)

function createNetworkRuntime(): LiveSocketRuntime {
  const socket = io(window.location.origin, {
    path: '/socket.io/',
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 3000,
    reconnectionAttempts: Infinity,
    timeout: 120000,
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
    start() {},
    dispose() {
      socket.disconnect()
    },
  }
}

const session = bootstrapLiveSession({
  search,
  view: createDomLiveView(document),
  createNetworkRuntime,
})

const pageDisposers = new DisposerStack()
let pageDisposed = false
const live2dStage = createLive2DStage(session.socket)
const liveAudio = createLiveAudioController(session.socket, document)
pageDisposers.add(() => session.dispose())
pageDisposers.add(() => liveAudio.dispose())
pageDisposers.add(() => live2dStage.dispose())
const disposePage = (): void => {
  if (pageDisposed) return
  pageDisposed = true
  pageDisposers.dispose()
}
window.addEventListener('beforeunload', disposePage, { once: true })
pageDisposers.add(() => window.removeEventListener('beforeunload', disposePage))

void live2dStage.ready.finally(() => {
  if (pageDisposed) return
  const notification = mountTtsFailoverReviewNotification(document, search, { autoplay: false })
  if (notification) {
    pageDisposers.add(() => notification.dispose())
    const volumes = parseReviewMouthTimeline(search.get('mouthTimeline'))
    live2dStage.playReviewAudio(notification.element, volumes)
  }
  const performanceReview = mountLive2DPerformanceReview(document, search, live2dStage)
  if (performanceReview) pageDisposers.add(() => performanceReview.dispose())
  session.start()
})

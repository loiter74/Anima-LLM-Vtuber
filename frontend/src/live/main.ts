import { io } from 'socket.io-client'
import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import { Events } from '@/constants/socket-events'
import type { Live2DAction } from '@/types/live2d'
import { createLiveController, type LiveSocket } from './controller'
import { createDomLiveView } from './view'
import './styles.css'

declare global {
  interface Window {
    PIXI: typeof PIXI
  }
}

window.PIXI = PIXI

const socketUrl = import.meta.env.VITE_API_URL || window.location.origin
const socket = io(socketUrl, {
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

createLiveController({
  socket: liveSocket,
  view: createDomLiveView(document),
})

async function initializeLive2D(): Promise<void> {
  const canvas = document.getElementById('live2dCanvas')
  const state = document.getElementById('modelStatus')
  if (!(canvas instanceof HTMLCanvasElement) || !state) return

  try {
    const app = new PIXI.Application({
      view: canvas,
      resizeTo: window,
      backgroundAlpha: 0,
      autoStart: true,
    })
    const model = await Live2DModel.from('/live2d/hiyori/Hiyori.model3.json', {
      autoInteract: false,
    })
    const baseWidth = model.width / model.scale.x
    const baseHeight = model.height / model.scale.y

    const layout = (): void => {
      const scale = Math.min(
        (app.screen.width * 0.88) / baseWidth,
        (app.screen.height * 0.82) / baseHeight,
      )
      model.scale.set(scale)
      model.anchor.set(0.5, 0.5)
      model.position.set(app.screen.width * 0.5, app.screen.height * 0.55)
    }

    app.stage.addChild(model)
    layout()
    window.addEventListener('resize', layout)
    socket.on(Events.CHAT.LIVE2D_ACTION, (action: Live2DAction) => {
      if (action.type === 'expression' && action.name) model.expression(action.name)
      if (action.type === 'motion' && action.group) model.motion(action.group, action.index ?? 0)
    })
    state.textContent = 'Live2D 已加载'
    state.dataset.state = 'live'
  } catch (error) {
    state.textContent = 'Live2D 加载失败'
    state.dataset.state = 'error'
    console.error('[Live] Live2D initialization failed', error)
  }
}

void initializeLive2D()

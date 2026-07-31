import { MINECRAFT_GAMEPLAY_LAYOUT, resolveMinecraftGameplayMode, toCssVariables } from './layout'

export interface MinecraftGameplayShellHandle {
  readonly element: HTMLElement
  dispose(): void
}

const PREVIEW_DANMAKU = [
  ['LUN077', '先做盾牌，稳一点！'],
  ['月见团子', '右边有铁矿，主播快看'],
  ['星野巡游者', '本小姐今天能全套铁装吗？'],
] as const

const BINDING_STATES = new Set(['disabled', 'waiting', 'attaching', 'following', 'degraded'])

function parseMouthTimeline(raw: string | null): number[] | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw)
    if (
      !Array.isArray(value) ||
      value.length === 0 ||
      value.length > 3_000 ||
      !value.every((sample) => Number.isFinite(sample) && sample >= 0 && sample <= 1)
    ) {
      return null
    }
    return value
  } catch {
    return null
  }
}

function parseLoopbackAudio(raw: string | null): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
      return null
    }
    return url.href
  } catch {
    return null
  }
}

function createElement<K extends keyof HTMLElementTagNameMap>(
  document: Document,
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag)
  element.className = className
  if (text !== undefined) element.textContent = text
  return element
}

function createPreviewWorld(document: Document): HTMLElement {
  const world = createElement(document, 'div', 'preview-world')
  world.setAttribute('aria-hidden', 'true')
  world.append(
    createElement(document, 'div', 'preview-sky'),
    createElement(document, 'div', 'preview-cloud preview-cloud-left'),
    createElement(document, 'div', 'preview-cloud preview-cloud-right'),
    createElement(document, 'div', 'preview-mountains'),
    createElement(document, 'div', 'preview-trees'),
    createElement(document, 'div', 'preview-ground'),
    createElement(document, 'div', 'preview-crosshair', '+'),
    createElement(document, 'div', 'preview-hotbar', '▣  ▣  ▣  ▣  ▣  ▣  ▣  ▣  ▣'),
  )
  return world
}

export function mountMinecraftGameplayShell(
  document: Document,
  search: URLSearchParams,
): MinecraftGameplayShellHandle {
  const mode = resolveMinecraftGameplayMode(search)
  const root = createElement(document, 'main', 'minecraft-gameplay')
  root.dataset.mode = mode
  for (const [name, value] of Object.entries(toCssVariables(MINECRAFT_GAMEPLAY_LAYOUT))) {
    root.style.setProperty(name, value)
  }

  const ambient = createElement(document, 'div', 'broadcast-ambient')
  ambient.setAttribute('aria-hidden', 'true')

  const television = createElement(document, 'section', 'television-frame')
  television.setAttribute('aria-label', 'Minecraft 游戏画面')
  const aperture = createElement(document, 'div', 'game-aperture')
  aperture.dataset.transparent = String(mode === 'overlay')
  if (mode === 'preview') aperture.append(createPreviewWorld(document))
  television.append(aperture)

  const status = createElement(document, 'div', 'possession-status')
  status.setAttribute('aria-label', '附身状态')
  const bindingState = search.get('bindingState')
  const safeBindingState =
    bindingState && BINDING_STATES.has(bindingState) ? bindingState : 'waiting'
  const confirmed = safeBindingState === 'following' && search.get('confirmed') === 'true'
  const target = search.get('target')?.slice(0, 32) || 'AnimettaBot'
  status.dataset.bindingState = safeBindingState
  status.dataset.confirmed = String(confirmed)
  status.append(
    createElement(document, 'span', 'status-dot'),
    createElement(
      document,
      'span',
      'status-copy',
      confirmed ? `已附身 LUN077 → ${target}` : '等待 LUN077 · 准备附身',
    ),
  )

  const danmaku = createElement(document, 'aside', 'game-danmaku')
  danmaku.setAttribute('aria-label', '实时弹幕')
  for (const [name, message] of PREVIEW_DANMAKU) {
    const item = createElement(document, 'div', 'danmaku-item')
    item.append(
      createElement(document, 'strong', 'danmaku-name', name),
      createElement(document, 'span', 'danmaku-copy', message),
    )
    danmaku.append(item)
  }

  const subtitle = createElement(
    document,
    'div',
    'game-subtitle',
    search.get('subtitle')?.slice(0, 120) || '本小姐今天一定要把铁装做出来。',
  )
  subtitle.setAttribute('aria-label', '直播字幕')

  const avatar = createElement(document, 'section', 'game-avatar')
  avatar.setAttribute('aria-label', 'Hiyori 主播')
  const canvas = createElement(document, 'canvas', 'game-avatar-canvas')
  canvas.id = 'live2dCanvas'
  const modelState = createElement(document, 'span', 'visually-hidden', 'Live2D 加载中')
  modelState.id = 'modelStatus'
  avatar.append(canvas, modelState)

  root.append(ambient, television, status, danmaku, subtitle, avatar)
  const audioUrl = parseLoopbackAudio(search.get('audio'))
  const mouthTimeline = parseMouthTimeline(search.get('mouthTimeline'))
  if (search.get('review') === '1' && audioUrl && mouthTimeline) {
    const runtime = createElement(document, 'section', 'minecraft-review-runtime')
    runtime.setAttribute('aria-hidden', 'true')
    runtime.dataset.mouthTimeline = JSON.stringify(mouthTimeline)
    runtime.dataset.lipSync = 'pending'
    const audio = createElement(document, 'audio', '')
    audio.id = 'reviewAudio'
    audio.src = audioUrl
    audio.preload = 'auto'
    audio.dataset.complete = 'pending'
    runtime.append(audio)
    root.append(runtime)
  }
  document.body.append(root)

  let disposed = false
  return {
    element: root,
    dispose(): void {
      if (disposed) return
      disposed = true
      root.remove()
    },
  }
}

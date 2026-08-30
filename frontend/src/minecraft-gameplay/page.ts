import { MINECRAFT_GAMEPLAY_LAYOUT, resolveMinecraftGameplayMode, toCssVariables } from './layout'
import { isStageIOView, type EvidenceRefView, type StageIOView } from '@/types/minecraft-stage'
import type { DanmakuItem } from '@/types/chat'
import type { LiveView } from '@/live/controller'
import type { PublicActivityView } from '@/shared/broadcast/publicActivity'
import { createDomPublicActivityView } from '@/shared/broadcast/publicActivityView'
import { resolvePublicMediaMode } from '@/shared/broadcast/mediaOwnership'

export type { StageIOView } from '@/types/minecraft-stage'

export interface MinecraftViewerStatusView {
  bindingState: string
  confirmed: boolean
  target: string
}

export interface MinecraftGameplayShellHandle extends LiveView, PublicActivityView {
  readonly element: HTMLElement
  updateWalkthrough(stages: readonly StageIOView[]): void
  setViewerStatus(status: MinecraftViewerStatusView): void
  dispose(): void
}

const PREVIEW_DANMAKU = [
  ['LUN077', '先做盾牌，稳一点！'],
  ['月见团子', '右边有铁矿，主播快看'],
  ['星野巡游者', '本小姐今天能全套铁装吗？'],
] as const

const BINDING_STATES = new Set(['disabled', 'waiting', 'attaching', 'following', 'degraded'])

const MAX_GAME_DANMAKU = 4

const SHOWCASE_STAGES = [
  ['scenario-setup', '场景布置'],
  ['capture-readiness', '观战与采集'],
  ['dialogue', '自然语言'],
  ['mission-admission', '任务接纳'],
  ['combat', '怪物交互'],
  ['construction', '建造验证'],
  ['autonomous-exploration', '自主探索'],
  ['discovery-acquisition', '新物品获取'],
  ['skill-learning-validation', '技能学习与验证'],
  ['skill-reuse', '可信技能复用'],
  ['progress-projection', '进度投影'],
  ['final-summary', '证据总结'],
] as const

const SHOWCASE_STAGE_IDS: ReadonlySet<string> = new Set(SHOWCASE_STAGES.map(([id]) => id))

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

function appendDanmakuItem(
  document: Document,
  parent: HTMLElement,
  name: string,
  message: string,
  messageId?: string,
): void {
  const item = createElement(document, 'div', 'danmaku-item')
  if (messageId) item.dataset.messageId = messageId
  item.append(
    createElement(document, 'strong', 'danmaku-name', name),
    createElement(document, 'span', 'danmaku-copy', message),
  )
  parent.append(item)
}

function danmakuMessageId(message: DanmakuItem): string {
  return (
    message.source_message_id ??
    `${message.timestamp}:${message.user_id}:${message.user_name}:${message.text}`
  )
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

function safeEvidenceIdentity(raw: string | null, fallback: string): string {
  return raw && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(raw) ? raw : fallback
}

function parseStageIO(raw: string | null): StageIOView[] {
  if (!raw || raw.length > 120_000) return []
  try {
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value) || value.length > SHOWCASE_STAGES.length) return []
    return value.filter(
      (item): item is StageIOView => isStageIOView(item) && SHOWCASE_STAGE_IDS.has(item.stage_id),
    )
  } catch {
    return []
  }
}

function compactValue(value: unknown): string {
  const serialized = JSON.stringify(value)
  if (serialized === undefined) return '—'
  return serialized.length > 180 ? `${serialized.slice(0, 177)}…` : serialized
}

function formatRef(ref: EvidenceRefView): string {
  return `${ref.artifact_id}#${ref.json_pointer}`
}

function appendStageDetail(
  document: Document,
  parent: HTMLElement,
  label: string,
  values: readonly string[],
): void {
  if (values.length === 0) return
  const row = createElement(document, 'div', 'showcase-stage-detail')
  row.append(
    createElement(document, 'span', 'showcase-stage-detail-label', label),
    createElement(document, 'span', 'showcase-stage-detail-value', values.join('；')),
  )
  parent.append(row)
}

function appendProjectedStageDetails(
  document: Document,
  item: HTMLElement,
  stage: StageIOView,
): void {
  const details = createElement(document, 'div', 'showcase-stage-details')
  const started = stage.started_at_ms ?? '—'
  const finished = stage.finished_at_ms ?? '—'
  appendStageDetail(document, details, '状态 / 时间', [
    `${stage.lifecycle} · ${started} → ${finished} ms`,
    stage.gameplay_evidence_eligible ? '任务内证据' : '任务外布置',
  ])
  appendStageDetail(document, details, '实际输入', (stage.input_refs ?? []).map(formatRef))
  appendStageDetail(
    document,
    details,
    '决策',
    [
      [stage.decision_source, stage.reason_code, stage.selected_strategy, stage.selected_capability]
        .filter((value): value is string => Boolean(value))
        .join(' · '),
    ].filter(Boolean),
  )
  if (stage.budget_ref) appendStageDetail(document, details, '预算', [formatRef(stage.budget_ref)])
  appendStageDetail(document, details, '实际输出', (stage.output_refs ?? []).map(formatRef))
  appendStageDetail(
    document,
    details,
    '状态变化',
    (stage.state_deltas ?? []).map(
      (delta) => `${delta.path}: ${compactValue(delta.before)} → ${compactValue(delta.after)}`,
    ),
  )
  appendStageDetail(
    document,
    details,
    '验证',
    (stage.predicates ?? []).map(
      (predicate) =>
        `${stage.verifier ?? predicate.predicate_id} · ${predicate.status} · actual=${compactValue(predicate.actual)}`,
    ),
  )
  appendStageDetail(document, details, '证据', (stage.evidence_refs ?? []).map(formatRef))
  appendStageDetail(
    document,
    details,
    '媒体',
    (stage.media ?? []).map(
      (media) => `${formatRef(media.evidence_ref)} @ ${media.captured_at_ms} ms`,
    ),
  )
  appendStageDetail(
    document,
    details,
    '检查点',
    (stage.checkpoints ?? []).map(
      (checkpoint) =>
        `${checkpoint.checkpoint_id} · ${checkpoint.lifecycle}${checkpoint.verifier ? ` · ${checkpoint.verifier}` : ''}`,
    ),
  )
  if (stage.failure) {
    appendStageDetail(document, details, '失败', [
      `${stage.failure.layer}/${stage.failure.code} · ${stage.failure.operator_action}`,
    ])
  }
  item.append(details)
}

interface ShowcaseTimelineHandle {
  readonly element: HTMLElement
  update(stages: readonly StageIOView[]): void
}

function createShowcaseTimeline(
  document: Document,
  search: URLSearchParams,
): ShowcaseTimelineHandle {
  const timeline = createElement(document, 'aside', 'showcase-timeline')
  timeline.setAttribute('aria-label', '任务证据时间线')
  const runId = safeEvidenceIdentity(search.get('runId'), 'run-pending')
  const missionId = safeEvidenceIdentity(search.get('missionId'), 'mission-pending')
  const requestedStage = search.get('stage')
  const currentStage =
    requestedStage && SHOWCASE_STAGE_IDS.has(requestedStage) ? requestedStage : 'scenario-setup'
  const completed = new Set(
    (search.get('completed') ?? '').split(',').filter((stageId) => SHOWCASE_STAGE_IDS.has(stageId)),
  )

  const heading = createElement(document, 'header', 'showcase-timeline-header')
  heading.append(
    createElement(document, 'strong', 'showcase-timeline-title', '证据时间线'),
    createElement(document, 'span', 'showcase-setup-boundary', '场景布置不计入任务成绩'),
    createElement(document, 'span', 'showcase-identity', runId),
    createElement(document, 'span', 'showcase-identity', missionId),
  )

  const list = createElement(document, 'ol', 'showcase-stage-list')
  const render = (stages: readonly StageIOView[]): void => {
    const projected = new Map(stages.map((stage) => [stage.stage_id, stage]))
    list.replaceChildren()
    for (const [index, [stageId, label]] of SHOWCASE_STAGES.entries()) {
      const item = createElement(document, 'li', 'showcase-stage')
      const stage = projected.get(stageId)
      const state = stage
        ? stage.lifecycle
        : completed.has(stageId)
          ? 'completed'
          : stageId === currentStage
            ? 'current'
            : 'pending'
      item.dataset.stageId = stageId
      item.dataset.stageState = state
      if (stageId === currentStage) item.setAttribute('aria-current', 'step')
      const summary = createElement(document, 'div', 'showcase-stage-summary')
      summary.append(
        createElement(document, 'span', 'showcase-stage-index', String(index + 1).padStart(2, '0')),
        createElement(document, 'span', 'showcase-stage-label', label),
      )
      item.append(summary)
      if (stage) appendProjectedStageDetails(document, item, stage)
      list.append(item)
    }
  }
  render(parseStageIO(search.get('stageIO')))
  timeline.append(heading, list)
  return { element: timeline, update: render }
}

export function mountMinecraftGameplayShell(
  document: Document,
  search: URLSearchParams,
): MinecraftGameplayShellHandle {
  const mode = resolveMinecraftGameplayMode(search)
  const review = search.get('review') === '1'
  const mediaMode = resolvePublicMediaMode(search, 'muted')
  const root = createElement(document, 'main', 'minecraft-gameplay')
  root.dataset.mode = mode
  root.dataset.review = String(review)
  root.dataset.media = mediaMode
  root.dataset.timeline = String(review && search.get('timeline') === '1')
  for (const [name, value] of Object.entries(toCssVariables(MINECRAFT_GAMEPLAY_LAYOUT))) {
    root.style.setProperty(name, value)
  }

  const ambient = createElement(document, 'div', 'broadcast-ambient')
  ambient.setAttribute('aria-hidden', 'true')

  const television = createElement(document, 'section', 'television-frame')
  television.setAttribute('aria-label', 'Minecraft 游戏画面')
  const aperture = createElement(document, 'div', 'game-aperture')
  aperture.dataset.transparent = String(mode === 'overlay')
  if (review && mode === 'preview') aperture.append(createPreviewWorld(document))
  television.append(aperture)

  const status = createElement(document, 'div', 'possession-status')
  status.setAttribute('aria-label', '附身状态')
  const bindingState = review ? search.get('bindingState') : null
  const safeBindingState =
    bindingState && BINDING_STATES.has(bindingState) ? bindingState : 'waiting'
  const confirmed = review && safeBindingState === 'following' && search.get('confirmed') === 'true'
  const target = (review ? search.get('target')?.slice(0, 32) : null) || 'AnimettaBot'
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
  const socketStatus = createElement(document, 'span', 'visually-hidden', '服务连接中')
  socketStatus.id = 'gameSocketStatus'
  socketStatus.dataset.state = 'connecting'
  status.append(socketStatus)

  const danmaku = createElement(document, 'aside', 'game-danmaku')
  danmaku.setAttribute('aria-label', '实时弹幕')
  if (review) {
    for (const [name, message] of PREVIEW_DANMAKU) {
      appendDanmakuItem(document, danmaku, name, message)
    }
  } else {
    danmaku.hidden = true
  }

  const fixtureSubtitle = review
    ? search.get('subtitle')?.slice(0, 120) || '本小姐今天一定要把铁装做出来。'
    : ''
  const subtitle = createElement(document, 'div', 'game-subtitle', fixtureSubtitle)
  subtitle.setAttribute('aria-label', '直播字幕')
  subtitle.hidden = !fixtureSubtitle

  const avatar = createElement(document, 'section', 'game-avatar')
  avatar.setAttribute('aria-label', '虹色 Mao 主播')
  const canvas = createElement(document, 'canvas', 'game-avatar-canvas')
  canvas.id = 'live2dCanvas'
  const modelState = createElement(document, 'span', 'visually-hidden', 'Live2D 加载中')
  modelState.id = 'modelStatus'
  avatar.append(canvas, modelState)

  const activityPanel = createElement(document, 'aside', 'public-activity-panel')
  activityPanel.id = 'publicActivityPanel'
  activityPanel.setAttribute('aria-label', '公开行动轨迹')
  activityPanel.hidden = true
  const activityHeader = createElement(document, 'header', 'public-activity-header')
  const activityHeading = createElement(document, 'div', '')
  activityHeading.append(
    createElement(document, 'div', 'public-activity-kicker', 'AGENCY TRACE'),
    createElement(document, 'h2', 'public-activity-title', '行动轨迹'),
  )
  activityHeader.append(activityHeading)
  const narration = createElement(document, 'section', 'public-narration-state')
  narration.id = 'publicNarrationState'
  narration.setAttribute('aria-label', '当前旁白')
  narration.setAttribute('aria-live', 'polite')
  narration.hidden = true
  const activitySummary = createElement(document, 'dl', 'public-activity-summary')
  activitySummary.setAttribute('aria-label', '当前行动摘要')
  for (const [label, id, fallback] of [
    ['当前意图', 'publicCurrentIntent', '等待任务'],
    ['最近观察', 'publicRecentObservation', '尚无观察'],
    ['下一阶段', 'publicNextPhase', '等待计划'],
  ] as const) {
    const slot = createElement(document, 'div', 'public-activity-summary-slot')
    const value = createElement(document, 'dd', '', fallback)
    value.id = id
    slot.append(createElement(document, 'dt', '', label), value)
    activitySummary.append(slot)
  }
  const activityList = createElement(document, 'ol', 'public-activity-list')
  activityList.id = 'publicActivityList'
  activityList.setAttribute('aria-live', 'polite')
  activityPanel.append(activityHeader, narration, activitySummary, activityList)

  const audioStatus = createElement(document, 'span', 'visually-hidden')
  audioStatus.id = 'audioStatus'
  audioStatus.hidden = true
  Object.assign(audioStatus.dataset, {
    playbackState: mediaMode === 'active' ? 'idle' : 'muted',
    playbackCount: '0',
    lastAudioTaskId: '',
    lastAudioKind: '',
    audioOwner: mediaMode,
    bgmState: 'off',
    lipSyncState: 'idle',
    lipSyncAppliedCount: '0',
    lipSyncPeak: '0',
    lastLipSyncTaskId: '',
    lastLipSyncAppliedAt: '',
  })
  const singingAudio = createElement(document, 'audio', '')
  singingAudio.id = 'singingAudio'
  singingAudio.preload = 'metadata'
  singingAudio.hidden = true

  root.append(
    ambient,
    television,
    status,
    danmaku,
    subtitle,
    activityPanel,
    avatar,
    audioStatus,
    singingAudio,
  )
  const timeline =
    review && search.get('timeline') === '1' ? createShowcaseTimeline(document, search) : null
  if (timeline) root.append(timeline.element)
  const audioUrl = review ? parseLoopbackAudio(search.get('audio')) : null
  const mouthTimeline = review ? parseMouthTimeline(search.get('mouthTimeline')) : null
  if (review && audioUrl && mouthTimeline) {
    const runtime = createElement(document, 'section', 'minecraft-review-runtime')
    runtime.setAttribute('aria-hidden', 'true')
    runtime.dataset.taskId = safeEvidenceIdentity(
      search.get('reviewTaskId'),
      'minecraft-review-audio',
    )
    runtime.dataset.mouthTimeline = JSON.stringify(mouthTimeline)
    runtime.dataset.lipSync = 'pending'
    const audio = createElement(document, 'audio', '')
    audio.id = 'reviewAudio'
    audio.src = audioUrl
    audio.preload = 'none'
    audio.dataset.complete = 'pending'
    runtime.append(audio)
    root.append(runtime)
  }
  document.body.append(root)
  const publicActivityView = createDomPublicActivityView(document)

  const setViewerStatus = (viewer: MinecraftViewerStatusView): void => {
    const bindingState = BINDING_STATES.has(viewer.bindingState) ? viewer.bindingState : 'degraded'
    const confirmed = bindingState === 'following' && viewer.confirmed
    const target = viewer.target.slice(0, 32) || 'AnimettaBot'
    status.dataset.bindingState = bindingState
    status.dataset.confirmed = String(confirmed)
    const copy = status.querySelector<HTMLElement>('.status-copy')
    if (copy) {
      copy.textContent = confirmed
        ? `已附身 LUN077 → ${target}`
        : bindingState === 'degraded'
          ? '观战连接异常 · 等待恢复'
          : '等待 LUN077 · 准备附身'
    }
  }

  let disposed = false
  return {
    element: root,
    renderMessages(messages: readonly DanmakuItem[]): void {
      danmaku.replaceChildren()
      for (const message of messages.slice(-MAX_GAME_DANMAKU)) {
        appendDanmakuItem(
          document,
          danmaku,
          message.user_name || '匿名观众',
          message.text,
          danmakuMessageId(message),
        )
      }
      danmaku.hidden = messages.length === 0
      danmaku.dataset.messageCount = String(messages.length)
    },
    setSocketState(state): void {
      const labels = {
        connecting: '服务连接中',
        connected: '服务已连接',
        disconnected: '服务已断开',
        error: '服务连接异常',
      } as const
      socketStatus.dataset.state = state
      socketStatus.textContent = labels[state]
      root.dataset.socketState = state
    },
    setLivestreamStatus(livestream): void {
      root.dataset.livestreamState = livestream.state
      root.dataset.livestreamGeneration = String(livestream.generation_id)
    },
    setBilibiliReplyEvidence(reply): void {
      root.dataset.lastBilibiliSourceMessageId = reply.source_message_id
      root.dataset.lastBilibiliReplyId = reply.reply_id
    },
    setBackground(): void {
      // The Minecraft aperture owns its game capture and never accepts a live-room background.
    },
    setSubtitle(text: string | null): void {
      subtitle.textContent = text ?? ''
      subtitle.hidden = !text
    },
    renderPublicActivities: publicActivityView.renderPublicActivities,
    setPublicNarration: publicActivityView.setPublicNarration,
    updateWalkthrough(stages: readonly StageIOView[]): void {
      timeline?.update(stages)
    },
    setViewerStatus,
    dispose(): void {
      if (disposed) return
      disposed = true
      root.remove()
    },
  }
}
